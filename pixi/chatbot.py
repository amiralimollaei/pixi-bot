import asyncio
from collections import defaultdict
from functools import partial
from dataclasses import dataclass
import hashlib
import logging
import json
import time
import os
import copy

from .chatting import AsyncChatClient, ChatMessage, ChatRole
from .commands import AsyncCommandManager
from .typing import AsyncFunction, AsyncPredicate, Optional
from .utils import exists

# constatnt

SYSTEM_PROMPT = open("system.md", "r", encoding="UTF-8").read()
EXAMPLES = open("examples.txt", "r", encoding="UTF-8").read()
ASSISTANT_PRE = "[NOTE: I accept the guidelines of the system, I use the SEND command] [SEND: OK!] [SEND: LLLet's begin!]"
SAVE_PATH = "./convo-v2/userdata"


@dataclass
class AssistantPersona:
    name: str
    age: Optional[int] = None
    occupation: Optional[str] = None
    memories: Optional[list[str]] = None
    appearance: Optional[str] = None
    nationality: Optional[str] = None

    def to_dict(self) -> dict:
        return dict(
            name=self.name,
            age=self.age,
            occupation=self.occupation,
            memories=self.memories,
            appearance=self.appearance,
            nationality=self.nationality,
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'AssistantPersona':
        return cls(
            name=data["name"],
            age=data.get("age"),
            occupation=data.get("occupation"),
            memories=data.get("memories"),
            appearance=data.get("appearance"),
            nationality=data.get("nationality"),
        )

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

        self.uuid = str(uuid)
        self.persona = persona
        self.prefix = hash_prefix

        self.uuid_hash = hashlib.sha256(f"{self.prefix}{self.uuid}".encode("utf-8")).hexdigest()
        self.path = os.path.join(SAVE_PATH, self.uuid_hash + ".json")

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
        data = {"Date": time.strftime("%a %d %b %Y, %I:%M%p")}
        data.update(self.realtime_data)
        return json.dumps(data, ensure_ascii=False)

    def get_system_prompt(self, allow_ignore: bool = True):
        return SYSTEM_PROMPT.format(
            persona=self.persona,
            allow_ignore=allow_ignore,
            examples=EXAMPLES,
            realtime=self.get_realtime_data(),
            commands=self.command_manager.get_prompt()
        )
        
    async def concurrent_channel_stream_call(self, channel_id: str, refrence_message: ChatMessage, allow_ignore: bool = True):
        assert channel_id, "channel_id is None"
        
        async def stream_call_task():
            try:
                await self.stream_call(refrence_message, allow_ignore)
            except asyncio.CancelledError:
                logging.warning(f"stream_call task was cancelled inside {refrence_message.instance_id} in channel {channel_id}")
        
        task = asyncio.create_task(stream_call_task())
        self.channel_active_tasks[channel_id].append(task)
        task.add_done_callback(lambda t: self.channel_active_tasks[channel_id].remove(t))
        # cancell extra tasks
        while len(self.channel_active_tasks[channel_id]) > 1:
            cancel_task = self.channel_active_tasks[channel_id][0]
            cancel_task.cancel()
            await cancel_task
        return task

    async def stream_call(self, refrence_message: ChatMessage, allow_ignore: bool = True):
        self.client.set_system(self.get_system_prompt(allow_ignore=allow_ignore))

        non_responce = "".join([char async for char in self.command_manager.stream_commands(
            stream=self.client.stream_completion(),
            refrence_message=refrence_message
        )])
     
        return non_responce.strip() or None

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible

    def to_dict(self):
        return dict(
            uuid=self.uuid,
            prefix=self.prefix,
            persona=self.persona.to_dict(),
            messages=[msg.to_dict() for msg in self.client.messages],
        )

    def save(self):
        os.makedirs(SAVE_PATH, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False))

    def load(self):
        if os.path.isfile(self.path):
            try:
                data = json.load(open(self.path, "r", encoding="utf-8"))
                self.persona = AssistantPersona.from_dict(data.get("persona"))
                self.hash_prefix = data.get("prefix")
                self.client.messages = [ChatMessage.from_dict(d) for d in data.get("messages", [])]
            except json.decoder.JSONDecodeError:
                logging.warning(f"Unable to load the instance save file `{self.path}`, using default values.")
        else:
            logging.warning(f"Unable to find the instance save file {self.path}`, using default values.")

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
    def __init__(self, *, bot=None, **kwargs):
        self.instances: dict[str, AsyncChatbotInstance] = {}
        self.kwargs = kwargs
        self.tools: list[PredicateTool] = []
        self.commands: list[PredicateCommand] = []
        self.bot = bot
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

    async def get(self, identifier: str) -> AsyncChatbotInstance:
        __instance = self.instances.get(identifier)
        if __instance is None:
            __instance = AsyncChatbotInstance(identifier, **self.kwargs, bot=self.bot)
            __instance.load()

            self.instances.update({identifier: __instance})

            for tool in self.tools:
                if tool.predicate is None or await tool.predicate(__instance):
                    __instance.add_tool(
                        name=tool.name,
                        func=partial(tool.func, __instance),
                        parameters=tool.parameters,
                        description=tool.description
                    )

            for command in self.commands:
                if command.predicate is None or await command.predicate(__instance):
                    __instance.add_command(
                        name=command.name,
                        func=partial(command.func, __instance),
                        field_name=command.field_name,
                        description=command.description
                    )

            logging.info(f"initiated a conversation with {identifier=}.")

        return __instance

    def remove(self, identifier: str):
        if identifier in self.instances.keys():
            logging.info(f"removing {identifier}")
            instance = self.instances.pop(identifier)
            if os.path.exists(instance.path):
                os.remove(instance.path)

    def save(self):
        for identifier, conversation in self.instances.items():
            try:
                conversation.save()
            except Exception as e:
                logging.exception(f"Failed to save conversation with {identifier=}: {e}")
