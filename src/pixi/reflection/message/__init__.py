from abc import ABC, abstractmethod
import dataclasses
from typing import Any

from ...caching.base import MediaCache
from ...enums import ChatType, Platform


@dataclasses.dataclass(frozen=True)
class ReflectionMessageAuthor:
    id: int
    first_name: str
    last_name: str
    display_name: str
    mention: str


@dataclasses.dataclass(frozen=True)
class ReflectionEnvironment:
    chat_id: int
    chat_title: str
    chat_type: ChatType
    forum_id: int
    is_forum: bool


@dataclasses.dataclass(frozen=True)
class AbstractMessage(ABC):
    content: str
    author: ReflectionMessageAuthor
    id: int
    environment: ReflectionEnvironment
    platform: Platform

    # hold a refrence of the original message for everything else that we didn't define here
    origin: Any

    @classmethod
    @abstractmethod
    def from_origin(cls, message) -> 'AbstractMessage': ...
    @abstractmethod
    async def send(self, content: str) -> 'AbstractMessage': ...
    @abstractmethod
    async def edit(self, content: str) -> 'AbstractMessage | None': ...
    @abstractmethod
    async def delete(self): ...
    @abstractmethod
    async def typing(self): ...
    @abstractmethod
    async def fetch_images(self) -> list[MediaCache]: ...
    @abstractmethod
    async def fetch_audio(self) -> list[MediaCache]: ...
    @abstractmethod
    async def fetch_refrences(self) -> 'AbstractMessage | None': ...
    @abstractmethod
    async def add_reaction(self, emoji: str): ...
    @abstractmethod
    async def send_file(self, filepath: str, filename: str, caption: str | None = None): ...

    @property
    def environment_id(self) -> str:
        # if the message is in a forum type environemnt (server, guild, channels group, etc.)
        if self.environment.is_forum:
            return f"forum#{self.environment.forum_id}"
        return f"chat#{self.environment.chat_id}"

    def get_chat_info(self) -> dict:
        return {"type": self.environment.chat_type, "name": self.environment.chat_title, "id": self.environment.chat_id}

    def is_inside_dm(self) -> bool:
        return self.environment.chat_type == ChatType.PRIVATE
