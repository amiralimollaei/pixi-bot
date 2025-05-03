import logging
import re
import os
import json
import time
import hashlib

from api.utils import exists

import api.chatting as Chat
from api import ChatClient

# constatnt

SYSTEM_PROMPT = open("preprompt3-short.md", "r", encoding="UTF-8").read()
REALTIME_PROMPT = "Here are the real-time data that you might need to answer questions, " + \
                "you don't have to mention them if they are not needed:\n" + \
                "```json\n{data}\n```"
EXAMPLES = open("examples3-short.md", "r", encoding="UTF-8").read()

ASSISTANT_PRE = "(NOTE: I accept the guidelines of the system)\nOK! [SEND]\nLLLet's begin! :) [SEND]"

# the maximum lenght of the conversation in tokens (Approx.), before it get's cut off
MAX_LENGTH = 32000

SAVE_PATH = "./convo-v2/userdata"

NOTES_PATTERN = re.compile(r"(?i)\s?\(\s?NOTE:[^)]*\s?\)\s?")

class LLMConversation:
    def __init__(self, uuid: int | str, persona: Chat.AssistantPersona, hash_prefix: str, messages: list[Chat.RoleMessage] = None):
        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(persona) and isinstance(persona, Chat.AssistantPersona), f"Invalid persona \"{persona}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."

        self.uuid = uuid
        self.persona = persona
        self.prefix = hash_prefix
        
        self.realtime_data = dict()
        self.is_notes_visible = False
        
        self.client = ChatClient(messages)
        if messages is not None:
            self.client.add_message(Chat.RoleMessage(Chat.Role.ASSISTANT, ASSISTANT_PRE))
    
    def set_messages(self, messages: list[Chat.RoleMessage]):
        assert isinstance(messages, list), f"Invalid messages \"{messages}\"."
        self.client.messages = messages
    
    def get_messages(self):
        return self.client.messages
    
    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_system_prompt(self, allow_ignore: bool = True):
        return SYSTEM_PROMPT.format(persona = self.persona, allow_ignore = allow_ignore) + f"\n{EXAMPLES}\n" + self.get_realtime_data()

    def get_realtime_data(self):
        data = {"time and date": time.strftime("%a %d %b %Y, %I:%M%p")}
        data.update(self.realtime_data)
        return REALTIME_PROMPT.format(data = json.dumps(data, ensure_ascii=False))

    def stream_ask(self, message: Chat.RoleMessage | str, allow_ignore: bool = True):
        self.client.set_system(self.get_system_prompt(allow_ignore = allow_ignore))

        response: str = ""
        for chunk in self.client.stream_ask(message):
            response += chunk

            clean_responce = response.replace("\\[", "[").replace("\\]", "]").strip()

            if "[SEND]" in clean_responce:
                splits = clean_responce.split("[SEND]")
                response = splits[1] if len(splits) > 1 else ""
                yield self.proccess_response(splits[0])
            
            if response.endswith("[NONE]"):
                if not allow_ignore:
                    response = response.replace("[NONE]", "")
                else:
                    response = ""
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
                self.persona = Chat.AssistantPersona.from_dict(data.get("persona"))
                self.hash_prefix = data.get("prefix")
                self.client.messages = [Chat.RoleMessage.from_dict(d) for d in data.get("messages") or []]
            except json.decoder.JSONDecodeError:
                logging.warning(f"Unable to load the save file: {fname}, using defaults.")
        else:
            logging.warning("Unable to find the save file, using defaults.")
        
    @classmethod
    def from_dict(cls, data: dict) -> 'LLMConversation':
        return cls(
            uuid = data.get("uuid"),
            persona = Chat.AssistantPersona.from_dict(data.get("persona")),
            hash_prefix = data.get("prefix"),
            messages = [Chat.RoleMessage.from_dict(d) for d in data.get("messages") or []]
        )

    def live_chat(self, message: str | Chat.RoleMessage, with_memory: bool = True, allow_ignore: bool = True):
        stream = self.stream_ask(message, allow_ignore = allow_ignore)
        if with_memory:
            responses = []
            for resp in stream:
                responses.append(resp)
                yield resp
            self.client.add_message(Chat.RoleMessage(
                Chat.Role.ASSISTANT,
                "\n".join([r + " [SEND]" for r in responses])
            ))
        else:
            for resp in stream:
                yield resp

if __name__ == "__main__":
    persona = Chat.AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    chat = LLMConversation(0, persona, "test")
    while True:
        query = input("You: ")
        for resp in chat.live_chat(query):
            print("LLM: " + resp)


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