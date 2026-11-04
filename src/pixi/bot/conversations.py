from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from contextlib import aclosing, contextmanager
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, overload

from pixi.ai.chatting.actions import ActionOutcome, AsyncActionManager
from pixi.ai.chatting.callbacks import AsyncAction, AsyncTool, InvocationContext
from pixi.ai.chatting.client import AsyncChatClient
from pixi.ai.chatting.persona import AssistantPersona
from pixi.async_utils import AsyncScheduler
from pixi.interfaces.messages import MessagesStorage
from pixi.model.chat import ChatMessage
from pixi.model.enums import ChatRole

if TYPE_CHECKING:
    from pixi.bot.client import PixiClient
    from pixi.interfaces.platform import PlatformMessage


class AsyncChatbotInstance(AsyncChatClient):
    def __init__(
        self,
        uuid: int | str,
        hash_prefix: str,
        *,
        store: MessagesStorage,
        persona: AssistantPersona,
        system_prompt_template: str,
        examples: str,
        tools=(),
        actions=(),
        bot: PixiClient | None = None,
        **client_kwargs,
    ):
        if not isinstance(uuid, (int, str)) or not uuid:
            raise ValueError(f'Invalid uuid "{uuid}".')
        if not isinstance(hash_prefix, str) or not hash_prefix:
            raise ValueError(f'Invalid hash_prefix "{hash_prefix}".')
        self.id = str(uuid)
        self.prefix = hash_prefix
        super().__init__(
            storage=store, history_key=f"{hash_prefix}:{self.id}", **client_kwargs
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self.persona = persona
        self.system_prompt_template = system_prompt_template
        self.examples = examples
        self.bot = bot

        self.realtime_data: dict = {}
        self.is_notes_visible = False
        self.actions_since_last_message = 0
        self.last_used_at = time.monotonic()
        self._active_users = 0

        if not self.storage.exists(self.history_key):
            self.add_message(
                ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content="[NOTE: I accept the guidelines of the system, I use the SEND to respond nicely] [SEND: OK!, Let's begin!]",
                )
            )

        self.scheduler = AsyncScheduler()
        self.action_manager = AsyncActionManager()
        self.channel_active_tasks: defaultdict[str, list[asyncio.Task]] = defaultdict(
            list
        )

        for tool in tools:
            if tool.should_register(self):
                self.add_tool(tool)
        for action in actions:
            if action.should_register(self):
                self.add_action(action)

    @contextmanager
    def use(self):
        """Keep this instance resident until the current operation finishes."""
        self._active_users += 1
        try:
            yield self
        finally:
            self._active_users -= 1
            self.last_used_at = time.monotonic()

    @property
    def is_busy(self) -> bool:
        return (
            self._active_users > 0
            or self.scheduler.pending_count > 0
            or any(
                not task.done()
                for tasks in self.channel_active_tasks.values()
                for task in tasks
            )
        )

    def schedule(
        self, id: str, delay: float, callback: Callable[[], Awaitable[None]]
    ) -> bool:
        async def run_callback():
            with self.use():
                await callback()

        with self.detached_history():
            return self.scheduler.schedule(id=id, delay=delay, callback=run_callback)

    def schedule_action(
        self,
        action: AsyncAction,
        value: str | None,
        action_context: InvocationContext,
        id: str,
        delay: float,
    ) -> bool:
        async def execute_scheduled():
            await self.action_manager.invoke_action(action, action_context, value)

        return self.schedule(id=id, delay=delay, callback=execute_scheduled)

    def cancel_schedule(self, id: str) -> bool:
        return self.scheduler.cancel(id)

    def cancel_all_schedules(self):
        self.scheduler.cancel_all()

    def add_action(self, action: AsyncAction):
        self.action_manager.add_action(action)

    def add_message(
        self, message: ChatMessage | str, default_role: ChatRole = ChatRole.USER
    ) -> ChatMessage:
        self.actions_since_last_message = 0
        self.last_used_at = time.monotonic()
        if isinstance(message, str):
            message = ChatMessage(default_role, message)
        if isinstance(message, ChatMessage):
            return super().add_message(message)
        raise TypeError(
            f"expected message to be a string or a ChatMessage, but got {type(message)}."
        )

    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_realtime_data(self):
        return json.dumps(
            self.realtime_data | dict(date=time.strftime("%a %d %b %Y, %I:%M%p")),
            ensure_ascii=False,
            indent=3,
        )

    def create_tool_context(
        self,
        reference_message: ChatMessage,
        platform_message: PlatformMessage | None = None,
    ) -> InvocationContext:
        return InvocationContext(
            reference_message=reference_message,
            parent_instance=self,
            platform_message=platform_message,
        )

    def get_system_prompt(self):
        return self.system_prompt_template.format(
            persona=self.persona,
            examples=self.examples,
            realtime=self.get_realtime_data(),
            actions=self.action_manager.get_prompt(),
        )

    async def stream_call(
        self,
        reference_message: ChatMessage,
        message: str | None = None,
        discard_history: bool = False,
        system_prompt: str | None = None,
        platform_message: PlatformMessage | None = None,
        outcome: ActionOutcome | None = None,
    ):
        if outcome is None:
            outcome = ActionOutcome()
        with self.use(), self.history_scope(discard_history=discard_history):
            if message:
                self.add_message(message)

            context = self.create_tool_context(reference_message, platform_message)
            async with aclosing(
                self._stream_completion(
                    system_prompt=system_prompt,
                    tool_context=context,
                )
            ) as completion:
                async with aclosing(
                    self.action_manager.consume(
                        stream=completion,
                        action_context=context,
                        outcome=outcome,
                    )
                ) as actions:
                    non_response = "".join([char async for char in actions])
            return non_response.strip() or None

    async def concurrent_channel_stream_call(
        self,
        channel_id: str,
        reference_message: ChatMessage,
        platform_message: PlatformMessage | None = None,
        outcome: ActionOutcome | None = None,
    ):
        assert channel_id, "channel_id is None"
        await self.cancel_channel_active_tasks(channel_id)

        async def stream_call_task():
            try:
                await self.stream_call(
                    reference_message,
                    platform_message=platform_message,
                    outcome=outcome,
                )
            except asyncio.CancelledError:
                self.logger.warning(
                    f"stream_call task was cancelled inside {self.id} in channel {channel_id}"
                )
                raise

        task = asyncio.create_task(stream_call_task())
        self.channel_active_tasks[channel_id].append(task)
        task.add_done_callback(
            lambda t: self.channel_active_tasks[channel_id].remove(t)
        )
        return task

    async def cancel_channel_active_tasks(self, channel_id: str):
        for task in self.channel_active_tasks[channel_id]:
            task.cancel()

    async def aclose(self) -> None:
        """Stop all consumers before their shared dependencies are closed."""
        tasks = [
            task for channel in self.channel_active_tasks.values() for task in channel
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, self.scheduler.aclose(), return_exceptions=True)

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible


class ChatbotInstanceRegistry:
    def __init__(
        self,
        hash_prefix: str,
        bot,
        *,
        store: MessagesStorage,
        persona: AssistantPersona,
        system_prompt_template: str,
        examples: str,
    ):
        self.hash_prefix = hash_prefix
        self.bot = bot
        self.store = store
        self.persona = persona
        self.system_prompt_template = system_prompt_template
        self.examples = examples
        self.instances: dict[str, AsyncChatbotInstance] = {}
        self.tools: list[AsyncTool] = []
        self.actions: list[AsyncAction] = []
        self.logger = logging.getLogger("ChatbotInstanceRegistry")

    def register_action(self, action: AsyncAction):
        self.actions.append(action)

    def register_tool(self, tool: AsyncTool):
        self.tools.append(tool)

    def new_instance(self, identifier: str, **kwargs) -> AsyncChatbotInstance:
        instance = AsyncChatbotInstance(
            identifier,
            self.hash_prefix,
            store=self.store,
            persona=self.persona,
            system_prompt_template=self.system_prompt_template,
            examples=self.examples,
            tools=self.tools,
            actions=self.actions,
            bot=self.bot,
            **kwargs,
        )
        self.instances[instance.id] = instance
        return instance

    @overload
    def get(
        self, identifier: str, or_create: Literal[True] = True, **kwargs
    ) -> AsyncChatbotInstance: ...

    @overload
    def get(
        self, identifier: str, or_create: Literal[False] = False, **kwargs
    ) -> AsyncChatbotInstance | None: ...

    def get(
        self, identifier: str, or_create: bool = True, **kwargs
    ) -> AsyncChatbotInstance | None:
        if instance := self.instances.get(identifier):
            instance.last_used_at = time.monotonic()
            return instance
        if or_create:
            instance = self.new_instance(identifier, **kwargs)
            self.logger.info("created new chatbot instance %s.", instance.id)
            return instance
        return None

    def evict_idle(self, idle_timeout: float) -> int:
        now = time.monotonic()
        evicted = 0
        for identifier in list(self.instances):
            instance = self.instances[identifier]
            if instance.is_busy or now - instance.last_used_at < idle_timeout:
                continue
            del self.instances[identifier]
            evicted += 1
            self.logger.info("Unloaded idle chatbot instance %s.", identifier)
        return evicted

    async def aclose(self) -> None:
        """Wait for every resident conversation to stop using dependencies."""
        await asyncio.gather(
            *(instance.aclose() for instance in tuple(self.instances.values()))
        )

    def remove(self, identifier: str):
        self.store.delete(f"{self.hash_prefix}:{identifier}")
        self.instances.pop(identifier, None)
