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
from .utils import exists

# constatnt

SYSTEM_PROMPT = open("system.md", "r", encoding="UTF-8").read()
EXAMPLES = open("examples.txt", "r", encoding="UTF-8").read()
ASSISTANT_PRE = "[NOTE: I accept the guidelines of the system, I use the SEND command] [SEND: OK!] [SEND: LLLet's begin!]"
SAVE_PATH = "./storage/userdata"


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
    path = os.path.join(SAVE_PATH, f"{hash_prefix}_{uuid_hash}.json")
    return path

class AsyncChatbotInstance:
    def __init__(self,
                 uuid: int | str,
                 persona: AssistantPersona,
                 hash_prefix: str,
                 messages: Optional[list[ChatMessage]] = None,
                 *,
                 bot=None,
                 **client_kwargs,
                 ):
        self.bot = bot
        assert self.bot

        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(persona) and isinstance(persona, AssistantPersona), f"Invalid persona \"{persona}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."

        self.scheduled_messages = []

        self.id = str(uuid)
        self.persona = persona
        self.prefix = hash_prefix

        self.path = get_instance_save_path(id=self.id, hash_prefix=self.prefix)

        self.realtime_data = dict()
        self.is_notes_visible = False
        self.command_manager = AsyncCommandManager()

        self.last_send_time = 0.0
        self.responded = False

        self.client = AsyncChatClient(messages, **client_kwargs)
        if messages is not None:
            self.client.add_message(ChatMessage(ChatRole.ASSISTANT, ASSISTANT_PRE, bot=self.bot))

        self.channel_active_tasks: defaultdict[str, list[asyncio.Task]] = defaultdict(list)

    def add_command(self, name: str, field_name: str, func: AsyncFunction, description: Optional[str] = None):
        self.command_manager.add_command(name, field_name, func, description)

    def add_tool(self, name: str, func: AsyncFunction, parameters: Optional[dict] = None, description: Optional[str] = None):
        """
        Register a tool (function) for tool calling.
        name: tool name (string)
        func: Callback
        parameters: OpenAI tool/function parameters schema (dict)
        description: description of the tool (string)
        """

        self.client.add_tool(
            name=name,
            func=func,
            parameters=parameters,
            description=description
        )

    def add_message(self, message: ChatMessage | str, default_role: ChatRole = ChatRole.USER) -> ChatMessage:
        """
        Add a message to the conversation.
        This is useful for initializing the conversation with existing messages.
        """
        if isinstance(message, str):
            message = ChatMessage(default_role, message, bot=self.bot)

        if isinstance(message, ChatMessage):
            message.bot = self.bot  # this is intended to be handled by this class
            self.client.add_message(message)
            return message
        else:
            raise TypeError(f"expected message to be a string or a ChatMessage, but got {type(message)}.")

    def set_messages(self, messages: list[ChatMessage]):
        assert isinstance(messages, list), f"Invalid messages \"{messages}\"."
        self.client.messages = messages

    def get_messages(self):
        return self.client.messages

    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def set_rearrange_predicate(self, predicate: AsyncPredicate):
        """
        Set a predicate function to rearrange messages based on a specific condition.
        This is useful for filtering messages by channel or other criteria.
        """
        assert callable(predicate), f"Predicate must be callable, got {predicate}."
        self.client.set_rearrange_predicate(predicate)

    def get_realtime_data(self):
        return json.dumps(self.realtime_data | dict(date=time.strftime("%a %d %b %Y, %I:%M%p")), ensure_ascii=False)

    def get_system_prompt(self, allow_ignore: bool = True):
        return SYSTEM_PROMPT.format(
            persona=self.persona,
            allow_ignore=allow_ignore,
            examples=EXAMPLES,
            realtime=self.get_realtime_data(),
            commands=self.command_manager.get_prompt()
        )

    async def concurrent_channel_stream_call(self, channel_id: str, reference_message: ChatMessage, allow_ignore: bool = True):
        assert channel_id, "channel_id is None"

        async def stream_call_task():
            try:
                await self.stream_call(reference_message, allow_ignore)
            except asyncio.CancelledError:
                logging.warning(
                    f"stream_call task was cancelled inside {reference_message.instance_id} in channel {channel_id}")

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
        self.client.set_system(self.get_system_prompt(allow_ignore=allow_ignore))

        non_responce = "".join([char async for char in self.command_manager.stream_commands(
            stream=self.client.stream_completion(),
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
            persona=self.persona.to_dict(),
            messages=[msg.to_dict() for msg in self.client.messages],
        )

    def save(self):
        os.makedirs(SAVE_PATH, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False))

    def load(self, not_found_ok: bool = False):
        if os.path.isfile(self.path):
            try:
                data = json.load(open(self.path, "r", encoding="utf-8"))
                self.persona = AssistantPersona.from_dict(data.get("persona"))
                self.hash_prefix = data.get("prefix")
                self.client.messages = [ChatMessage.from_dict(d) for d in data.get("messages", [])]
            except json.decoder.JSONDecodeError:
                logging.warning(f"Unable to load the instance save file `{self.path}`, using default values.")
        else:
            if not_found_ok:
                logging.info(f"Unable to find the instance save file {self.path}`, using default values.")
            else:
                raise FileNotFoundError(f"Unable to find the instance save file {self.path}`.")

    @classmethod
    def from_dict(cls, data: dict, **client_kwargs) -> 'AsyncChatbotInstance':
        return cls(
            uuid=data["uuid"],
            persona=AssistantPersona.from_dict(data["persona"]),
            hash_prefix=data["prefix"],
            messages=[ChatMessage.from_dict(d) for d in data.get("messages", [])],
            **client_kwargs
        )


class CachedAsyncChatbotFactory:
    def __init__(self, *, parent=None, hash_prefix: str, **kwargs):
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

    async def new_instance(self, identifier: str) -> AsyncChatbotInstance:
        instance = AsyncChatbotInstance(identifier, **self.kwargs, hash_prefix=self.hash_prefix, bot=self.bot)

        for tool in self.tools:
            if tool.predicate is None or await tool.predicate(instance):
                instance.add_tool(
                    name=tool.name,
                    func=partial(tool.func, instance),
                    parameters=tool.parameters,
                    description=tool.description
                )

        for command in self.commands:
            if command.predicate is None or await command.predicate(instance):
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

            logging.info(f"initiated a conversation with {identifier=}.")

        return instance

    def remove(self, identifier: str):
        logging.info(f"removing {identifier}")
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
                logging.exception(f"Failed to save conversation with {identifier=}: {e}")
