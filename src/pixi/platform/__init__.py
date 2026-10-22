from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from ..caching import MediaCacheSystem
from ..model.enums import ChatType, Platform


@dataclass(frozen=True)
class ReflectionMessageAuthor:
    id: int
    first_name: str
    last_name: str
    display_name: str
    mention: str


@dataclass(frozen=True)
class ReflectionEnvironment:
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

    async def fetch_images(self) -> list[bytes]: ...

    async def fetch_audio(self) -> list[bytes]: ...

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

class PlatformProvider(Protocol):
    """Platform provider contract, with shared realtime metadata assembly.

    Select a concrete provider with get_platform_provider(platform), then
    instantiate it without arguments. start_async runs until cancelled; callers
    must await close_async to release the platform connection.
    """

    platform: Platform

    def __init__(self): ...

    def run(self) -> None:
        """Run the bot (blocking)."""
        ...

    async def start_async(self) -> None:
        """Run the bot until cancelled."""
        ...

    async def close_async(self) -> None:
        """Stop the bot and release its connection."""
        ...

    async def wait_until_ready(self) -> None:
        """Wait until the bot is ready to handle messages."""
        ...

    def register_on_message_event(self, function: Callable) -> None: ...

    def register_slash_command(self, name: str, function: Callable,
                               description: str | None = None) -> None: ...

    def get_guild_info(self, message: PlatformMessage) -> dict: ...

    def get_thread_info(self, message: PlatformMessage) -> dict: ...

    def get_realtime_data(self, message: PlatformMessage) -> dict:
        data = dict(
            platform=self.platform,
            chat_info=message.get_chat_info()
        )

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


def get_platform_provider(platform: Platform) -> type[PlatformProvider]:
    """Select a platform provider without importing the other platform's SDK."""
    assert type(platform) == Platform
    try:
        match platform:
            case Platform.DISCORD:
                from .discord import DiscordProvider
                return DiscordProvider
            case Platform.TELEGRAM:
                from .telegram import TelegramProvider
                return TelegramProvider
            case _:
                raise RuntimeError(f"PlatformProvider unknown platform {platform}.")
    except ImportError as error:
        raise RuntimeError(
            f"PlatformProvider for {platform} is not available; install its optional dependencies."
        ) from error
