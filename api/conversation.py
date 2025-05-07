import logging
import re
import os
import json
import time
import hashlib

from .utils import exists

from .chatting import AssistantPersona, Role, RoleMessage
from .client import ChatClient

# constatnt

SYSTEM_PROMPT = open("system.md", "r", encoding="UTF-8").read()
EXAMPLES = open("examples.txt", "r", encoding="UTF-8").read()

ASSISTANT_PRE = "(NOTE: I accept the guidelines of the system)\nOK! [SEND]\nLLLet's begin! :) [SEND]"

# the maximum lenght of the conversation in tokens (Approx.), before it get's cut off
MAX_LENGTH = 32000

SAVE_PATH = "./convo-v2/userdata"

NOTES_PATTERN = re.compile(r"(?i)\s?\(\s?NOTE:[^)]*\s?\)\s?")

class LLMConversation:
    def __init__(self, uuid: int | str, persona: AssistantPersona, hash_prefix: str, messages: list[RoleMessage] = None):
        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(persona) and isinstance(persona, AssistantPersona), f"Invalid persona \"{persona}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."

        self.uuid = uuid
        self.persona = persona
        self.prefix = hash_prefix
        
        self.realtime_data = dict()
        self.is_notes_visible = False
        
        self.client = ChatClient(messages)
        if messages is not None:
            self.client.add_message(RoleMessage(Role.ASSISTANT, ASSISTANT_PRE))
    
    def set_messages(self, messages: list[RoleMessage]):
        assert isinstance(messages, list), f"Invalid messages \"{messages}\"."
        self.client.messages = messages
    
    def get_messages(self):
        return self.client.messages
    
    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_realtime_data(self):
        data = {"time and date": time.strftime("%a %d %b %Y, %I:%M%p")}
        data.update(self.realtime_data)
        return json.dumps(data, ensure_ascii=False)
    
    def get_system_prompt(self, allow_ignore: bool = True):
        return SYSTEM_PROMPT.format(
            persona = self.persona,
            allow_ignore = allow_ignore,
            examples = EXAMPLES,
            realtime = self.get_realtime_data()
        )

    def stream_ask(self, message: RoleMessage | str, allow_ignore: bool = True):
        self.client.set_system(self.get_system_prompt(allow_ignore = allow_ignore))

        response: str = ""
        for chunk in self.client.stream_ask(message):
            response += chunk

            response = response.replace("\\[", "[").replace("\\]", "]")

            if response.strip().endswith("[SEND]"):
                yield self.proccess_response(response[:-6])
                response = ""
            
            if response.strip().endswith("[NONE]"):
                if not allow_ignore:
                    response = ""
                else:
                    response = response[:-6]

        if response != "":
            yield self.proccess_response(response)

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible

    def proccess_response(self, msg: str):
        if "[NONE]" in msg:
            return "NO_RESPONSE"
        
        if "[SEND]" in msg:
            msg = msg.replace("[NONE]", "")

        if not self.is_notes_visible:
            msg = NOTES_PATTERN.sub("", msg)

        return msg.strip()

    def get_uuid_hash(self) -> str:
        return hashlib.sha256(f"{self.prefix}{self.uuid}".encode("utf-8")).hexdigest()
    
    def get_file(self) -> str:
        return os.path.join(SAVE_PATH, self.get_uuid_hash() + ".json")
    
    def to_dict(self):
        return dict(
            uuid = self.uuid,
            prefix = self.prefix,
            persona = self.persona.to_dict(),
            messages = [msg.to_dict() for msg in self.client.messages],
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
                self.client.messages = [RoleMessage.from_dict(d) for d in data.get("messages") or []]
            except json.decoder.JSONDecodeError:
                logging.warning(f"Unable to load the save file: {fname}, using defaults.")
        else:
            logging.warning("Unable to find the save file, using defaults.")
        
    @classmethod
    def from_dict(cls, data: dict) -> 'LLMConversation':
        return cls(
            uuid = data.get("uuid"),
            persona = AssistantPersona.from_dict(data.get("persona")),
            hash_prefix = data.get("prefix"),
            messages = [RoleMessage.from_dict(d) for d in data.get("messages") or []]
        )

    def live_chat(self, message: str | RoleMessage, with_memory: bool = True, allow_ignore: bool = True):
        stream = self.stream_ask(message, allow_ignore = allow_ignore)
        if with_memory:
            responses = []
            for resp in stream:
                responses.append(resp)
                yield resp
            self.client.add_message(RoleMessage(
                Role.ASSISTANT,
                "\n".join([r + " [SEND]" for r in responses])
            ))
        else:
            for resp in stream:
                yield resp

class ConversationStorage:
    def __init__(self, **kwargs):
        self.conversations: dict[str, LLMConversation] = {}
        self.kwargs = kwargs

    def get(self, identifier: str) -> LLMConversation:
        convo = self.conversations.get(identifier, LLMConversation(identifier, **self.kwargs))
        if identifier not in self.conversations:
            convo.load()
            self.update(identifier, convo)
            logging.info(f"initiated a conversation with {identifier}.")
        return convo

    def update(self, identifier: str, conversation: LLMConversation):
        self.conversations.update({identifier: conversation})

    def remove(self, identifier: str):
        if identifier in self.conversations.keys():
            del self.conversations[identifier]

        fname = LLMConversation(identifier, **self.kwargs).get_file()
        if os.path.exists(fname):
            os.remove(fname)

    def save(self):
        for identifier, conversation in self.conversations.items():
            try:
                conversation.save()
            except Exception as e:
                logging.warning(f"Failed to save conversation {identifier}: {e}")


if __name__ == "__main__":
    persona = AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    conversation = LLMConversation(0, persona, "test")
    while True:
        query = input("You: ")
        for resp in conversation.live_chat(query):
            print("LLM: " + resp)