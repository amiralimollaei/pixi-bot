import dataclasses
from typing import Any, Protocol

from ...caching import MediaCache
from ...model.enums import ChatType, Platform


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


class PlatformMessage(Protocol):
    """Platform-neutral message contract with shared chat metadata helpers.

    Concrete messages own their storage and wrap the platform SDK's origin.
    """
    content: str | None
    author: ReflectionMessageAuthor
    id: int
    environment: ReflectionEnvironment
    platform: Platform

    # hold a refrence of the original message for everything else that we didn't define here
    origin: Any

    @classmethod
    def from_origin(cls, message) -> 'PlatformMessage': ...

    async def send(self, content: str) -> 'PlatformMessage': ...

    async def edit(self, content: str) -> 'PlatformMessage | None': ...

    async def delete(self) -> None: ...

    async def typing(self) -> None: ...

    async def fetch_images(self) -> list[MediaCache]: ...

    async def fetch_audio(self) -> list[MediaCache]: ...

    async def fetch_reference(self) -> 'PlatformMessage | None': ...

    async def add_reaction(self, emoji: str) -> None: ...

    async def send_file(self, filepath: str, filename: str, caption: str | None = None) -> None: ...

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
