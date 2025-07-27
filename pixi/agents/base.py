import json
import logging
import os

from ..chatting import AsyncChatClient


class AgentBase:
    def __init__(self, **client_kwargs):
        self.client = AsyncChatClient(**client_kwargs)

    def to_dict(self) -> dict:
        raise NotImplementedError("tried to call `to_dict` but it is not implemented.")

    @classmethod
    def from_dict(cls, data: dict) -> 'AgentBase':
        raise NotImplementedError("tried to call `from_dict` but it is not implemented.")

    def save_json(self, file: str):
        with open(file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def from_file(cls, file: str) -> 'AgentBase':
        if os.path.isfile(file):
            with open(file, "rb") as f:
                data = json.load(f)
            return cls.from_dict(data)
        else:
            logging.warning("Unable to find agent save file at `{file}`, creating a new instance.")
            instance = cls()
            instance.save_json(file)
            return instance