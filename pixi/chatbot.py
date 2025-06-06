from dataclasses import dataclass
import logging
import os
import json
import time
import hashlib

from .commands import AsyncCommand, AsyncCommandManager
from .chatting import ChatRole, ChatMessage
from .chatclient import AsyncChatClient, Callback
from .utils import exists

# constatnt

SYSTEM_PROMPT = open("system.md", "r", encoding="UTF-8").read()
EXAMPLES = open("examples.txt", "r", encoding="UTF-8").read()
ASSISTANT_PRE = "[NOTE: I accept the guidelines of the system] [SEND: OK!] [SEND: LLLet's begin!]"
SAVE_PATH = "./convo-v2/userdata"

@dataclass
class AssistantPersona:
    name: str
    age: int = None
    occupation: str = None
    memories: list[str] = None
    appearance: str = None
    nationality: str = None

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
            name=data.get("name"),
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


class AsyncChatbotInstance:
    def __init__(self,
                 uuid: int | str,
                 persona: AssistantPersona,
                 hash_prefix: str,
                 messages: list[ChatMessage] = None,
                 **client_kwargs,
                 ):
        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(persona) and isinstance(persona, AssistantPersona), f"Invalid persona \"{persona}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."

        self.uuid = uuid
        self.persona = persona
        self.prefix = hash_prefix

        self.realtime_data = dict()
        self.is_notes_visible = False
        self.command_manager = AsyncCommandManager()

        self.client = AsyncChatClient(messages, **client_kwargs)
        if messages is not None:
            self.client.add_message(ChatMessage(ChatRole.ASSISTANT, ASSISTANT_PRE))

    def add_command(self, command: AsyncCommand):
        self.command_manager.add_command(command)

    def add_command(self, name: str, field_name: str, function: Callback, descriptioon: str = None):
        self.command_manager.add_command(name, field_name, function, descriptioon)

    def add_tool(self, name: str, func: Callback, parameters: dict = None, description: str = None):
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

    def set_messages(self, messages: list[ChatMessage]):
        assert isinstance(messages, list), f"Invalid messages \"{messages}\"."
        self.client.messages = messages

    def get_messages(self):
        return self.client.messages

    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_realtime_data(self):
        data = {"Date": time.strftime("%a %d %b %Y, %I:%M%p")}
        data.update(self.realtime_data)
        return json.dumps(data, ensure_ascii=False, indent=4)

    def get_system_prompt(self, allow_ignore: bool = True):
        return SYSTEM_PROMPT.format(
            persona=self.persona,
            allow_ignore=allow_ignore,
            examples=EXAMPLES,
            realtime=self.get_realtime_data(),
            commands=self.command_manager.get_prompt()
        )

    async def stream_call(self, message: ChatMessage | str, allow_ignore: bool = True, temporal: bool = False):
        self.client.set_system(self.get_system_prompt(allow_ignore=allow_ignore))

        response = ""
        async for char in self.command_manager.stream_commands(self.client.stream_ask(message, temporal=temporal)):
            response += char

        return response.strip() or None

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible

    def get_uuid_hash(self) -> str:
        return hashlib.sha256(f"{self.prefix}{self.uuid}".encode("utf-8")).hexdigest()

    def get_file(self) -> str:
        return os.path.join(SAVE_PATH, self.get_uuid_hash() + ".json")

    def to_dict(self):
        return dict(
            uuid=self.uuid,
            prefix=self.prefix,
            persona=self.persona.to_dict(),
            messages=[msg.to_dict() for msg in self.client.messages],
        )

    def save(self):
        # we make sure the save directory exists because we can't write to it, if it doesn't exist
        os.makedirs(SAVE_PATH, exist_ok=True)
        with open(self.get_file(), "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False))

    def load(self):
        fname = self.get_file()
        if os.path.exists(fname):
            try:
                data = json.load(open(fname, "r", encoding="utf-8"))
                self.persona = AssistantPersona.from_dict(data.get("persona"))
                self.hash_prefix = data.get("prefix")
                self.client.messages = [ChatMessage.from_dict(d) for d in data.get("messages", [])]
            except json.decoder.JSONDecodeError:
                logging.warning(f"Unable to load the instance save file `{fname}`, using default values.")
        else:
            logging.warning(f"Unable to find the instance save file {fname}`, using default values.")

    @classmethod
    def from_dict(cls, data: dict, **client_kwargs) -> 'AsyncChatbotInstance':
        return cls(
            uuid=data.get("uuid"),
            persona=AssistantPersona.from_dict(data.get("persona")),
            hash_prefix=data.get("prefix"),
            messages=[ChatMessage.from_dict(d) for d in data.get("messages", [])],
            **client_kwargs
        )


class CachedAsyncChatbotFactory:
    def __init__(self, **kwargs):
        self.conversations: dict[str, AsyncChatbotInstance] = {}
        self.kwargs = kwargs
        self.tools = []
        self.commands = []

    def register_command(self, name: str, field_name: str, function: Callback, descriptioon: str = None):
        self.commands.append(dict(
            name=name,
            field_name=field_name,
            function=function,
            descriptioon=descriptioon
        ))

    def register_tool(self, name: str, func: Callback, parameters: dict = None, description: str = None):
        """
        Register a tool (function) for tool calling.
        name: tool name (string)
        func: Callback
        parameters: OpenAI tool/function parameters schema (dict)
        description: description of the tool (string)
        """

        self.tools.append(dict(
            name=name,
            func=func,
            parameters=parameters,
            description=description
        ))

    def get(self, identifier: str) -> AsyncChatbotInstance:
        convo = self.conversations.get(identifier, AsyncChatbotInstance(identifier, **self.kwargs))
        if identifier not in self.conversations:
            convo.load()
            self.update(identifier, convo)
            logging.info(f"initiated a conversation with {identifier=}.")

        for tool_kwargs in self.tools:
            convo.add_tool(**tool_kwargs)

        for command_kwargs in self.commands:
            convo.add_command(**command_kwargs)

        return convo

    def update(self, identifier: str, conversation: AsyncChatbotInstance):
        self.conversations.update({identifier: conversation})

    def remove(self, identifier: str):
        if identifier in self.conversations.keys():
            del self.conversations[identifier]

        fname = AsyncChatbotInstance(identifier, **self.kwargs).get_file()
        if os.path.exists(fname):
            os.remove(fname)

    def save(self):
        for identifier, conversation in self.conversations.items():
            try:
                conversation.save()
            except Exception as e:
                logging.exception(f"Failed to save conversation with {identifier=}")
