import re
import os
import json
import time
import hashlib

from api.utils import exists

import api.chatting as Chat
from api import ChatClient
from api.memory import MemoryAgent

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

class LLMChat2:
    def __init__(self, uuid: int, persona: Chat.AssistantPersona, hash_prefix: str, messages: list[Chat.RoleMessage] = None):
        assert exists(uuid) and isinstance(uuid, int), f"Invalid uuid \"{uuid}\"."
        assert exists(persona) and isinstance(persona, Chat.AssistantPersona), f"Invalid persona \"{persona}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."

        self.uuid = uuid
        self.persona = persona
        self.prefix = hash_prefix
        
        self.realtime_data = dict()
        self.is_notes_visible = False
        
        self.memory = None
        
        self.client = ChatClient(messages)
        if messages is not None:
            self.client.add_message(Chat.RoleMessage(Chat.Role.ASSISTANT, ASSISTANT_PRE))
            
    
    def set_memory_module(self, memory: MemoryAgent):
        self.memory = memory
        self.client.register_tool(
            name = "add_or_retrieve_memory",
            func = self.add_or_retrieve_memory,
            parameters = dict(
                type = "object",
                properties = {
                    "query": {
                        "type": "string",
                        "description": "The query, which is used to identify the memory. (Optional)",
                    },
                    "memory": {
                        "type": "string",
                        "description": "The memory to be added. (Optional)",
                    }
                },
                required = [],
                additionalProperties = False
            ),
            description = "Adds a memory to the your memories, so that you can query it later, or retrieves a memory from the your memories, \
            you must also state the name of the user in the query and the memory."
        )
        
    def add_or_retrieve_memory(self, query: str = None, memory: str = None):
        result = None
        if query is not None:
            result = self.memory.retrieve_memories(query)
        if memory is not None:
            self.memory.add_memory(memory)
        
        return result
    
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

    def get_uuid_hash(self):
        return hashlib.sha256(f"{self.prefix}{self.uuid}".encode("utf-8")).hexdigest()
    
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
        
        uuid_hath = self.get_uuid_hash()
        fname = os.path.join(SAVE_PATH, f"{uuid_hath}.json")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False))
        
        if self.memory is not None:
            fname = os.path.join(SAVE_PATH, f"memories.json")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.memory.to_dict(), ensure_ascii=False))

    @classmethod
    def from_dict(cls, data: dict) -> 'LLMChat2':
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
            self.save()
        else:
            for resp in stream:
                yield resp

if __name__ == "__main__":
    persona = Chat.AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    chat = LLMChat2(0, persona, "test")
    while True:
        query = input("You: ")
        for resp in chat.live_chat(query):
            print("LLM: " + resp)
