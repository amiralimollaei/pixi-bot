import dataclasses
from typing import Any

from ...caching.base import MediaCache
from ...enums import Platform, ChatType, Messages


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
class ReflectionMessageBase:
    content: str
    author: ReflectionMessageAuthor
    id: int
    environment: ReflectionEnvironment
    platform: Platform

    # hold a refrence of the original message for everything else that we didn't define here
    origin: Any

    @classmethod
    def from_origin(cls, message) -> 'ReflectionMessageBase':
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("__to_reflectionmessage", cls.__name__))

    async def send(self, content: str) -> 'ReflectionMessageBase':
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("send", self.__class__.__name__))

    async def edit(self, content: str) -> 'ReflectionMessageBase | None':
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("edit", self.__class__.__name__))

    async def delete(self):
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("delete", self.__class__.__name__))

    async def typing(self):
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("typing", self.__class__.__name__))

    async def fetch_images(self) -> list[MediaCache]:
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("fetch_images", self.__class__.__name__))

    async def fetch_audio(self) -> list[MediaCache]:
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("fetch_audio", self.__class__.__name__))

    async def fetch_refrences(self) -> 'ReflectionMessageBase | None':
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("fetch_message_reply", self.__class__.__name__))

    async def add_reaction(self, emoji: str):
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("add_reaction", self.__class__.__name__))

    async def send_file(self, filepath: str, filename: str, caption: str | None = None):
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("send_file", self.__class__.__name__))
    
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