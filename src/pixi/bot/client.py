import asyncio
import logging
import math
from contextlib import closing
from dataclasses import asdict
from typing import Any, Callable, Coroutine
from uuid import uuid4

from ..ai.agents import AgentBase
from ..ai.chatting.callbacks import AsyncAction, AsyncTool
from ..ai.chatting.persona import AssistantPersona
from ..ai.rag.client import AsyncRAGClient
from ..model.chat import ChatMessageMeta
from ..model.config import (IdFilter, LlamaEmbeddingModelConfig,
                            LlamaLanguageModelConfig, OpenAIEmbeddingModelConfig,
                            OpenAILanguageModelConfig, PixiFeatures)
from ..model.enums import ChatRole
from ..interfaces.messages import MessagesStorage
from ..interfaces.models import ChatModel
from ..interfaces.platform import PlatformMessage, PlatformProvider
from .conversations import AsyncChatbotInstance, ChatbotInstanceRegistry
from .news import NewsBackgroundTask

# constants

SUMMON_KEYWORDS = ["pixi", "پیکسی"]


# helper functions

def remove_prefixes(text: str):
    text = text.strip()
    for keyword in SUMMON_KEYWORDS:
        for i in range(len(keyword)-1):
            text = text.removeprefix("!" + keyword[:len(keyword)-i])
    return text


class PixiClient:
    def __init__(
        self,
        platform_provider: PlatformProvider,
        *,
        chat_model: ChatModel,
        model: OpenAILanguageModelConfig | LlamaLanguageModelConfig,
        messages_storage: MessagesStorage,
        persona: AssistantPersona,
        system_prompt_template: str,
        examples: str,
        helper_chat_model: ChatModel | None = None,
        helper_model: OpenAILanguageModelConfig | LlamaLanguageModelConfig | None = None,
        embedding_model: OpenAIEmbeddingModelConfig | LlamaEmbeddingModelConfig | None = None,
        rag_factory: Callable[[], AsyncRAGClient] | None = None,
        news_task_factory: Callable[[AsyncChatbotInstance], NewsBackgroundTask] | None = None,
        features: PixiFeatures = PixiFeatures.default(),
        environment_filter: IdFilter | None = None,
        instance_idle_timeout: float = 900.0,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        if not math.isfinite(instance_idle_timeout) or instance_idle_timeout <= 0:
            raise ValueError("instance_idle_timeout must be a positive finite number of seconds.")

        self.platform_provider = platform_provider
        self.chat_model = chat_model
        self.model = model
        self.helper_chat_model = helper_chat_model or chat_model
        self.helper_model = helper_model or model
        self.embedding_model = embedding_model
        self._rag_factory = rag_factory
        self._news_task_factory = news_task_factory
        self._stopping = False
        self.features = features
        self.instance_idle_timeout = instance_idle_timeout
        self.environment_filter = environment_filter if environment_filter is not None else IdFilter.allow()
        self.pre_startup_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []
        self.post_startup_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []
        self.shutdown_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []
        self.datasets = []
        self.messages_storage = messages_storage
        self.conversations = ChatbotInstanceRegistry(
            platform_provider.platform,
            self,
            store=messages_storage,
            persona=persona,
            system_prompt_template=system_prompt_template,
            examples=examples,
        )

        if news_task_factory is not None:
            self.register_post_startup_hook(self._start_news_instances)

        self.__register_builtin_slash_commands()
        self.platform_provider.register_on_message_event(self.on_message)


    async def _start_news_instances(self):
        self.logger.info("Starting proactive news for available guilds...")
        for guild in await self.platform_provider.get_available_guilds():
            instance_id = f"forum#{guild.id}"
            self.logger.info(f" - \"{guild.name}\" (members: {guild.member_count})")
            self.get_chatbot_instance(instance_id)

    async def _evict_idle_instances(self):
        while True:
            await asyncio.sleep(min(60.0, self.instance_idle_timeout))
            self.conversations.evict_idle(self.instance_idle_timeout)


    def register_tool(self, tool: AsyncTool):
        if PixiFeatures.ToolCalling not in self.features:
            self.logger.warning("tried to register a tool, but tool calls are disabled, ignoring...")
            return

        self.conversations.register_tool(tool)

    def register_action(self, action: AsyncAction):
        self.conversations.register_action(action)

    def create_agent_instance[A: AgentBase](self, agent_cls: type[A], **agent_kwargs) -> A:
        history_key = agent_kwargs.pop("history_key", str(uuid4()))
        return agent_cls(
            chat_model=self.helper_chat_model,
            model=self.helper_model,
            storage=self.messages_storage,
            history_key=history_key,
            log_tool_calls=PixiFeatures.ToolLogging in self.features,
            **agent_kwargs,
        )

    def create_rag_client(self) -> AsyncRAGClient:
        if self._rag_factory is None:
            raise RuntimeError("No embedding model is configured.")
        return self._rag_factory()

    def register_slash_command(self, name: str, function, description: str | None = None):
        async def checked_function(message: PlatformMessage):
            environment_id = message.environment_id
            if not self.is_environment_allowed(environment_id):
                self.logger.warning(
                    f"ignoring slash command in {environment_id} because it is not in the allowed places.")
                await message.send("This command is not allowed here.")
                return
            await function(message)
        self.platform_provider.register_slash_command(name, checked_function, description)

    async def typing_delay(self, message: PlatformMessage, delay: float):
        delay_served = 0.0
        while delay_served < delay:
            await message.typing()
            await asyncio.sleep(3.0)
            delay_served += 3.0





    def __register_builtin_slash_commands(self):
        async def notes_slash_command(message: PlatformMessage):
            if not await self.platform_provider.is_dm_or_admin(message):
                await message.send("You must be a guild admin or use this in DMs.")
                return
            try:
                environment_id = message.environment_id
                is_notes_visible = self.get_chatbot_instance(environment_id).toggle_notes()
                notes_message = "Notes are now visible." if is_notes_visible else "Notes are no longer visible"
                await message.send(notes_message)
            except Exception:
                self.logger.exception(f"Failed to toggle notes")
                await message.send("Failed to toggle notes.")

        async def reset_slash_command(message: PlatformMessage):
            if not await self.platform_provider.is_dm_or_admin(message):
                await message.send("You must be a guild admin or use this in DMs.")
                return

            environment_id = message.environment_id

            instance = self.conversations.get(environment_id, or_create=False)
            if instance:
                instance.cancel_all_schedules()
                instance.stop_news_background_task()
            self.conversations.remove(environment_id)
            self.logger.info(f"the conversation in {environment_id} has been reset, all scheduled tasks cancelled.")

            await message.send("Wha- Where am I?!")

        self.register_slash_command(
            name="reset",
            function=reset_slash_command,
            description="Reset the conversation."
        )

        self.register_slash_command(
            name="notes",
            function=notes_slash_command,
            description="See pixi's thoughts"
        )

    def get_chatbot_instance(self, identifier: str) -> AsyncChatbotInstance:
        instance = self.conversations.get(
            identifier,
            chat_model=self.chat_model,
            model=self.model,
            log_tool_calls=PixiFeatures.ToolLogging in self.features
        )
        assert instance
        if (
            self._news_task_factory is not None
            and instance.forum_id is not None
            and instance.news_task is None
            and not self._stopping
        ):
            instance.news_task = self._news_task_factory(instance)
            instance.news_task.start()
        return instance

    async def pixi_resp(
        self,
        instance: AsyncChatbotInstance,
        reference_message: ChatMessageMeta,
        platform_message: PlatformMessage,
    ):
        if self._stopping:
            return False, True
        message = platform_message

        channel_id = message.environment.chat_id

        cancelled = False
        try:
            # concurrent_channel_stream_call handles overlapping requests automatically
            # killing tasks that are not done and restarting the request every time untill
            # one task finishes before the next request
            #
            # this way we can handle situations where the user is sending messages too quickly
            # with less tokens, but may increase response time, and killing tasks may result in
            # lost progress and http errors.
            #
            # TODO: find a solution to the above
            try:
                task = await instance.concurrent_channel_stream_call(
                    channel_id=str(channel_id),
                    reference_message=reference_message,
                    platform_message=platform_message,
                )
                while not task.done():
                    try:
                        await message.typing()
                        await asyncio.sleep(3)
                    except OSError:
                        self.logger.warning("OSError occurred while sending typing status")
                    except Exception:
                        self.logger.exception("an error occurred while sending typing status")
                noncall_result = await task
                if noncall_result:
                    self.logger.warning(f"{noncall_result=}")
            except asyncio.CancelledError:
                cancelled = True
        except Exception:
            self.logger.exception(f"Unknown error while responding to a message in {instance.id}.")
            raise

        return instance.action_manager.is_visible_actions_taken(), cancelled

    async def pixi_resp_retry(
        self,
        instance: AsyncChatbotInstance,
        chat_message: ChatMessageMeta,
        platform_message: PlatformMessage,
        num_retry: int = 10,
    ):
        """Retry requests while each failed stream discards its own uncommitted history delta."""
        instance.add_message(chat_message)
        for i in range(num_retry):
            try:
                responded, cancelled = await self.pixi_resp(
                    instance, reference_message=chat_message, platform_message=platform_message,
                )
                if responded or cancelled:
                    return True
                else:
                    self.logger.warning("model didn't respond to a message. (invalid, requesting a response)")
                    # ask the model to respond again
                    instance.add_message(
                        "[SYSTEM]: You didn't respond, if this is intentional use the SEND action with no value.")
            except Exception:
                self.logger.exception(f"There was an error in `pixi_resp`, Retrying ({i}/{num_retry})")

    def is_environment_allowed(self, identifier: str) -> bool:
        """
        Check if the environment identifier is allowed to be processed.
        """
        return self.environment_filter.is_allowed(identifier)

    async def should_respond(self, message: PlatformMessage) -> bool:
        # we should not process our own messages again
        if self.platform_provider.is_message_from_the_bot(message):
            return False

        environment_id = message.environment_id
        if not self.is_environment_allowed(environment_id):
            self.logger.warning(f"ignoring message in {environment_id} because it's not in an allowed environment.")
            return False

        if self.platform_provider.is_bot_mentioned(message) or message.is_inside_dm():
            return True

        message_text = message.content
        if message_text is None:
            message_text = ""

        # check if the message contains a summon word or a prefixed command
        is_keyword_present = False
        for keyword in SUMMON_KEYWORDS:
            if keyword in message_text.lower():
                is_keyword_present = True
                break
        is_prefixed = message_text.lower().startswith(tuple(["!" + k for k in SUMMON_KEYWORDS]))

        return is_prefixed or is_keyword_present

    async def __add_reply_metadata(self, instance: AsyncChatbotInstance, metadata: dict, message: PlatformMessage):
        # process reply reference
        reply_message = await message.fetch_reference()
        if reply_message is not None and reply_message.content is not None:
            reply_message_text = remove_prefixes(reply_message.content)
            # if the reply is to the last message in the instance, we don't need to do anything.
            reply_optimization = -1
            last_message = instance.last_message
            last_matches = (
                last_message is not None
                and last_message.content is not None
                and reply_message_text in last_message.content
            )
            if last_matches:
                reply_optimization = 2
            else:
                with closing(instance.iter_messages(reverse=True)) as messages:
                    if any(
                        msg.content is not None and reply_message_text in msg.content
                        for msg in messages
                    ):
                        reply_optimization = 1
            if reply_optimization == 2:
                # completely ignore reply context
                self.logger.debug(f"completely ignore reply context for {message.environment_id=}")
            elif reply_message and self.platform_provider.is_message_from_the_bot(reply_message):
                if reply_optimization == 1:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": "[YOU]",
                        "partial_content": reply_message_text[:64]
                    }
                else:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": "[YOU]",
                        "message": reply_message_text
                    }
            else:
                if reply_optimization == 1:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": asdict(reply_message.author),
                        "partial_message": reply_message_text[:64]
                    }
                else:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": asdict(reply_message.author),
                        "message": reply_message_text
                    }

    async def on_message(self, message: PlatformMessage):
        if not await self.should_respond(message):
            return

        message_text = message.content
        if message_text is None:
            message_text = ""

        message_text = remove_prefixes(message_text)
        environment_id = message.environment_id

        instance = self.get_chatbot_instance(environment_id)

        with instance.use():
            metadata = dict(
                from_user=asdict(message.author)
            )
            await self.__add_reply_metadata(instance, metadata, message)

            def rearrage_predicate(msg: ChatMessageMeta):
                msg_channel_id = msg.channel_id
                current_channel_id = message.environment.chat_id

                if msg_channel_id is None or current_channel_id is None:
                    return False
                return msg_channel_id == current_channel_id

            instance.update_realtime(self.platform_provider.get_realtime_data(message))
            instance.set_rearrange_predicate(rearrage_predicate)

            # convert everything into `ChatMessageMeta`
            chat_message = ChatMessageMeta(
                role=ChatRole.USER,
                content=message_text,
                metadata=metadata,
                image_hashes=await message.fetch_images() if PixiFeatures.ImageSupport in self.features else [],
                audio_hashes=await message.fetch_audio() if PixiFeatures.AudioSupport in self.features else [],
                channel_id=message.environment.chat_id,
            )

            await self.pixi_resp_retry(instance, chat_message, platform_message=message)

    def register_pre_startup_hook(self, hook: Callable[..., Coroutine[Any, Any, Any]]):
        """Register an async awaitable to run before the bot connects to Discord/Telegram.

        The hook will be awaited concurrently before the platform connection starts.
        This allows running async initialization code (e.g., database migrations,
        cache warming, API pre-checks) before the bot begins handling messages.
        """
        self.pre_startup_hooks.append(hook)

    def register_post_startup_hook(self, hook: Callable[..., Coroutine[Any, Any, Any]]):
        """Register an async awaitable to run after the bot connects to Discord/Telegram.

        The hook will be awaited concurrently after the platform connection starts.
        This allows running async initialization code (e.g., database migrations,
        cache warming, API pre-checks) after the bot begins handling messages.
        """
        self.post_startup_hooks.append(hook)

    def register_shutdown_hook(self, hook: Callable[..., Coroutine[Any, Any, Any]]):
        """Release external resources when the bot stops."""
        self.shutdown_hooks.append(hook)

    async def __post_startup_task(self):
        await self.platform_provider.wait_until_ready()
        if self.post_startup_hooks:
            self.logger.info(f"Running {len(self.post_startup_hooks)} post-startup hook(s)...")
            await asyncio.gather(*(f() for f in self.post_startup_hooks))
            self.logger.info("All post-startup hooks completed.")

    async def start(self):
        """Run startup hooks and the platform, releasing dependencies on exit."""
        background_tasks = []
        try:
            if self.pre_startup_hooks:
                self.logger.info(f"Running {len(self.pre_startup_hooks)} pre-startup hook(s)...")
                await asyncio.gather(*(hook() for hook in self.pre_startup_hooks))
                self.logger.info("All pre-startup hooks completed.")

            post_task = asyncio.create_task(self.__post_startup_task())
            background_tasks.append(post_task)
            background_tasks.append(
                asyncio.create_task(self._evict_idle_instances(), name="idle-instance-eviction")
            )
            await self.platform_provider.start_async()
            await post_task
        except asyncio.CancelledError:
            pass
        finally:
            self._stopping = True
            for task in background_tasks:
                task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)
            try:
                await self.conversations.aclose()
            finally:
                try:
                    await self.platform_provider.close_async()
                finally:
                    if self.shutdown_hooks:
                        await asyncio.gather(*(hook() for hook in self.shutdown_hooks))

    def run(self):
        """Run the bot (blocking with async support for startup hooks)."""
        asyncio.run(self.start())
