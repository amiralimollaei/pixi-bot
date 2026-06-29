import json
import logging
import os
from typing import Optional

from ..chatting import AsyncChatClient


class AgentBase:
    def __init__(self, *, client: Optional[AsyncChatClient] = None, **client_kwargs):
        self.client = client or AsyncChatClient(**client_kwargs)

    def to_dict(self) -> dict:
        return dict(
            client = self.client.state_dict()
        )

    @classmethod
    def from_dict(cls, data: dict, **client_kwargs) -> 'AgentBase':
        client = AsyncChatClient(**client_kwargs)
        client.load_state_dict(data["client"])
        return cls(
            client = client
        )

    def save_json(self, file: str):
        with open(file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def from_file(cls, file: str, **client_kwargs) -> 'AgentBase':
        if os.path.isfile(file):
            with open(file, "rb") as f:
                data = json.load(f)
            return cls.from_dict(data, **client_kwargs)
        else:
            logging.warning(f"Unable to find agent save file at `{file}`, creating a new instance.")
            instance = cls()
            instance.save_json(file)
            return instance

    def format_query(self, query: str):
        return query
    
    async def execute_query(self, query: str, temporal=True):
        response = ""
        async for char in self.client.stream_ask(self.format_query(query), temporal=temporal):
            response += char
        return response.strip()