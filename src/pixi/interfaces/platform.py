from typing import Callable, Protocol

from ..model.enums import ChatType, Platform
from ..model.platform import (
    ChannelMeta,
    GuildMeta,
    PlatformEnvironment,
    PlatformMessageAuthor,
)


class PlatformMessage(Protocol):
    """Platform-neutral message contract with shared chat metadata helpers."""

    content: str | None
    author: PlatformMessageAuthor
    id: int
    environment: PlatformEnvironment
    platform: Platform

    async def send(self, content: str) -> 'PlatformMessage': ...

    async def edit(self, content: str) -> 'PlatformMessage | None': ...

    async def delete(self) -> None: ...

    async def typing(self) -> None: ...

    async def fetch_images(self) -> list[bytes]: ...

    async def fetch_audio(self) -> list[bytes]: ...

    async def fetch_reference(self) -> 'PlatformMessage | None': ...

    async def add_reaction(self, emoji: str) -> None: ...

    async def send_file(self, filepath: str, filename: str, caption: str | None = None) -> None: ...

    @property
    def environment_id(self) -> str:
        if self.environment.is_forum:
            return f"forum#{self.environment.forum_id}"
        return f"chat#{self.environment.chat_id}"

    def get_chat_info(self) -> dict:
        return {"type": self.environment.chat_type, "name": self.environment.chat_title, "id": self.environment.chat_id}

    def is_inside_dm(self) -> bool:
        return self.environment.chat_type == ChatType.PRIVATE


class PlatformProvider(Protocol):
    """Platform provider contract with shared realtime metadata assembly."""

    platform: Platform

    def __init__(self): ...

    def run(self) -> None: ...

    async def start_async(self) -> None: ...

    async def close_async(self) -> None: ...

    async def wait_until_ready(self) -> None: ...

    def register_on_message_event(self, function: Callable) -> None: ...

    def register_slash_command(self, name: str, function: Callable,
                               description: str | None = None) -> None: ...

    def get_guild_info(self, message: PlatformMessage) -> dict: ...

    def get_thread_info(self, message: PlatformMessage) -> dict: ...

    def get_realtime_data(self, message: PlatformMessage) -> dict:
        data = dict(platform=self.platform, chat_info=message.get_chat_info())
        if guild_info := self.get_guild_info(message):
            data["guild_info"] = guild_info
        if thread_info := self.get_thread_info(message):
            data["thread_info"] = thread_info
        return data

    def can_read_history(self, chat_id: int) -> bool: ...

    def is_message_from_the_bot(self, message: PlatformMessage) -> bool: ...

    def is_bot_mentioned(self, message: PlatformMessage) -> bool: ...

    async def is_dm_or_admin(self, message: PlatformMessage) -> bool: ...

    async def send_file(self, chat_id: int, filepath: str, filename: str,
                        caption: str | None = None) -> None: ...

    async def get_user_avatar(self, user_id: int) -> bytes | None: ...

    async def fetch_channel_history(self, channel_id: int, n: int = 10) -> list[dict]: ...

    async def fetch_forum_channels(self, forum_id: int) -> list[ChannelMeta]: ...

    async def send_message(self, chat_id: int, text: str) -> None: ...

    async def get_available_guilds(self) -> list[GuildMeta]: ...
