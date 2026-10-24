from dataclasses import dataclass
from typing import Optional

from .enums import ChatType


@dataclass(frozen=True)
class PlatformMessageAuthor:
    id: int
    first_name: str
    last_name: str
    display_name: str
    mention: str


@dataclass(frozen=True)
class PlatformEnvironment:
    chat_id: int
    chat_title: str
    chat_type: ChatType
    forum_id: int
    is_forum: bool


@dataclass(frozen=True)
class ChannelMeta:
    id: int
    name: str
    mention: Optional[str] = None


@dataclass(frozen=True)
class GuildMeta:
    id: int
    name: str
    member_count: Optional[int] = None
