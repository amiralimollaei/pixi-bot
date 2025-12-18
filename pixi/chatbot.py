import asyncio
from collections import defaultdict
from functools import partial
from dataclasses import asdict, dataclass
import hashlib
import logging
import json
import time
import os

from .chatting import AsyncChatClient, ChatMessage, ChatRole
from .commands import AsyncCommandManager
from .typing import AsyncFunction, AsyncPredicate, Optional
from .utils import PixiPaths, exists, open_resource


@dataclass
class AssistantPersona:
    name: str
    age: Optional[int] = None
    location: Optional[str] = None
    appearance: Optional[str] = None
    background: Optional[str] = None
    likes: Optional[str] = None
    dislikes: Optional[str] = None
    online: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'AssistantPersona':
        return cls(**data)

    @classmethod
    def from_json(cls, file: str) -> 'AssistantPersona':
        with open(file, "rb") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def __str__(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class PredicateTool:
    name: str
    func: AsyncFunction
    parameters: Optional[dict] = None
    description: Optional[str] = None
    predicate: Optional[AsyncPredicate] = None


@dataclass
class PredicateCommand:
    name: str
    field_name: str
    func: AsyncFunction
    description: str
    predicate: Optional[AsyncPredicate] = None


def get_instance_save_path(id: str, hash_prefix: str):
    uuid_hash = hashlib.sha256(f"{hash_prefix}_{id}".encode("utf-8")).hexdigest()
    path = str(PixiPaths.userdata() / f"{hash_prefix}_{uuid_hash}.json")
    return path


class AsyncChatbotInstance(AsyncChatClient):
    def __init__(self,
                 uuid: int | str,
                 hash_prefix: str,
                 *,
                 bot=None,
                 resource_folder: str | None = None,
                 **client_kwargs,
                 ):
        
        super().__init__(**client_kwargs)

        self.logger = logging.getLogger(self.__class__.__name__)

        self.bot = bot
        assert self.bot

        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."
        assert not exists(resource_folder) or (exists(resource_folder) and isinstance(
            resource_folder, str)), f"Invalid resource_folder \"{resource_folder}\"."

        self.id = str(uuid)
        self.prefix = hash_prefix
        self.path = get_instance_save_path(id=self.id, hash_prefix=self.prefix)

        # load resources
        self.persona = AssistantPersona.from_dict(
            json.load(open_resource("persona.json", "r"))
        )
        self.system_prompt_template: str = open_resource("system.md", "r").read()
        self.examples: str = open_resource("examples.txt", "r").read()

        # runtime states
        self.realtime_data = dict()
        self.is_notes_visible = False
        self.command_manager = AsyncCommandManager()

        if not self.messages:
            self.add_message(ChatMessage(
                role=ChatRole.ASSISTANT,
                content="[NOTE: I accept the guidelines of the system, I use the SEND command to respond nicely] [SEND: OK!, Let's begin!]",
                bot=self.bot
            ))

        self.channel_active_tasks: defaultdict[str, list[asyncio.Task]] = defaultdict(list)

    def add_command(self, name: str, field_name: str, func: AsyncFunction, description: Optional[str] = None):
        self.command_manager.add_command(name, field_name, func, description)

    def add_message(self, message: ChatMessage | str, default_role: ChatRole = ChatRole.USER) -> ChatMessage:
        """
        Add a message to the conversation, and adds a reference to the bot to the messages as well.
        
        if message is a string, tries to determine the role of the message based on the last message recieved.
        """
        if isinstance(message, str):
            message = ChatMessage(default_role, message, bot=self.bot)

        if isinstance(message, ChatMessage):
            message.bot = self.bot  # this is intended to be handled by this class
            return super().add_message(message)
        else:
            raise TypeError(f"expected message to be a string or a ChatMessage, but got {type(message)}.")

    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_realtime_data(self):
        return json.dumps(self.realtime_data | dict(date=time.strftime("%a %d %b %Y, %I:%M%p")), ensure_ascii=False)

    def get_system_prompt(self, allow_ignore: bool = True):
        return self.system_prompt_template.format(
            persona=self.persona,
            allow_ignore=allow_ignore,
            examples=self.examples,
            realtime=self.get_realtime_data(),
            commands=self.command_manager.get_prompt()
        )

    async def concurrent_channel_stream_call(self, channel_id: str, reference_message: ChatMessage, allow_ignore: bool = True):
        assert channel_id, "channel_id is None"

        async def stream_call_task():
            try:
                await self.stream_call(reference_message, allow_ignore)
            except asyncio.CancelledError:
                self.logger.warning(
                    f"stream_call task was cancelled inside {reference_message.instance_id} in channel {channel_id}"
                )

        task = asyncio.create_task(stream_call_task())
        self.channel_active_tasks[channel_id].append(task)
        task.add_done_callback(lambda t: self.channel_active_tasks[channel_id].remove(t))
        # cancell extra tasks
        while len(self.channel_active_tasks[channel_id]) > 1:
            cancel_task = self.channel_active_tasks[channel_id][0]
            cancel_task.cancel()
            await cancel_task
        return task

    async def stream_call(self, reference_message: ChatMessage, allow_ignore: bool = True):
        self.set_system(self.get_system_prompt(allow_ignore=allow_ignore))

        non_responce = "".join([char async for char in self.command_manager.stream_commands(
            stream=self.stream_completion(),
            reference_message=reference_message
        )])

        return non_responce.strip() or None

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible

    def to_dict(self):
        return dict(
            uuid=self.id,
            prefix=self.prefix,
            messages=[msg.to_dict() for msg in self.messages],
        )

    def save(self):
        os.makedirs(PixiPaths.userdata(), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False))

    def load(self, not_found_ok: bool = False):
        if os.path.isfile(self.path):
            try:
                data = json.load(open(self.path, "r", encoding="utf-8"))
                self.hash_prefix = data.get("prefix")
                self.messages = [ChatMessage.from_dict(d) for d in data.get("messages", [])]
            except json.decoder.JSONDecodeError:
                self.logger.warning(f"Unable to load the instance save file `{self.path}`, using default values.")
        else:
            if not_found_ok:
                self.logger.info(f"Unable to find the instance save file {self.path}`, using default values.")
            else:
                raise FileNotFoundError(f"Unable to find the instance save file {self.path}`.")


class CachedAsyncChatbotFactory:
    def __init__(self, *, parent=None, hash_prefix: str, **kwargs):
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.instances: dict[str, AsyncChatbotInstance] = {}
        self.kwargs = kwargs
        self.hash_prefix = hash_prefix
        self.tools: list[PredicateTool] = []
        self.commands: list[PredicateCommand] = []
        self.bot = parent
        assert self.bot

    def register_command(self, command: PredicateCommand):
        """
        Register a command

        commands are inline tools with only one parameter that can be used by all models even without tool
        calling capabilities, their descriptions are dynamically added to the system prompt at runtime
        """

        self.commands.append(command)

    def register_tool(self, tool: PredicateTool):
        """
        Register a tool (function) for tool calling.
        """

        self.tools.append(tool)

    async def __execute_predicate_if_present(self, predicate: AsyncPredicate | None, *args, **kwargs) -> bool:
        if predicate is None:
            return True
        return await predicate(*args, **kwargs)

    async def new_instance(self, identifier: str) -> AsyncChatbotInstance:
        instance = AsyncChatbotInstance(identifier, **self.kwargs, hash_prefix=self.hash_prefix, bot=self.bot)

        # register all the tools for the newly created instance
        for tool in self.tools:
            if not await self.__execute_predicate_if_present(tool.predicate, instance):
                continue
            instance.add_tool(
                name=tool.name,
                func=partial(tool.func, instance),
                parameters=tool.parameters,
                description=tool.description
            )

        # register all the commands for the newly created instance
        for command in self.commands:
            if not await self.__execute_predicate_if_present(command.predicate, instance):
                continue
            instance.add_command(
                name=command.name,
                func=partial(command.func, instance),
                field_name=command.field_name,
                description=command.description
            )

        return instance

    def cache_instance(self, instance: AsyncChatbotInstance):
        self.instances.update({instance.id: instance})

    async def get(self, identifier: str) -> AsyncChatbotInstance | None:
        cached_instance = self.instances.get(identifier)
        if cached_instance:
            return cached_instance
        instance = await self.new_instance(identifier)
        try:
            instance.load(not_found_ok=False)
            # cache the instance
            self.cache_instance(instance)
            return instance
        except FileNotFoundError:
            return None

    async def get_or_create(self, identifier: str) -> AsyncChatbotInstance:
        instance = self.instances.get(identifier)
        if instance is None:
            instance = await self.new_instance(identifier)
            instance.load(not_found_ok=True)
            # cache the instance
            self.cache_instance(instance)
            self.logger.info(f"initiated a conversation with {identifier=}.")
        return instance

    def remove(self, identifier: str):
        self.logger.info(f"removing {identifier}")
        save_path = get_instance_save_path(id=identifier, hash_prefix=self.hash_prefix)
        if os.path.exists(save_path):
            os.remove(save_path)
        if identifier in self.instances.keys():
            del self.instances[identifier]

    def save(self):
        for identifier, conversation in self.instances.items():
            try:
                conversation.save()
            except Exception as e:
                self.logger.exception(f"Failed to save conversation with {identifier=}: {e}")
