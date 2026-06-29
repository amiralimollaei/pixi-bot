import logging
from typing import Callable

from .message import ReflectionMessageBase
from ..enums import Platform, ChatType
from ..caching.base import MediaCache


class ReflectionAPI:
    def __init__(self, platform: Platform):
        self.logger = logging.getLogger(self.__class__.__name__)
        
        assert type(platform) == Platform
        self.platform = platform
        self.reflection_message_cls: type[ReflectionMessageBase] | None = None

        self.logger.debug(f"initializing ReflectionAPI for {self.platform}...")
        try:
            match platform:
                case Platform.DISCORD:
                    from .discord import DiscordReflectionAPI
                    self._ref = DiscordReflectionAPI()
                    from .message.discord import DiscordReflectionMessage
                    self.reflection_message_cls = DiscordReflectionMessage
                case Platform.TELEGRAM:
                    from .telegram import TelegramReflectionAPI
                    self._ref = TelegramReflectionAPI()
                    from .message.telegram import TelegramReflectionMessage
                    self.reflection_message_cls = TelegramReflectionMessage
                case _:
                    raise RuntimeError(f"ReflectionAPI unknown platform {self.platform}.")
        except ImportError:
            raise RuntimeError(
                f"ReflectionAPI for {self.platform} is not available, maybe you forgot to install its dependecies?")
        self.logger.debug(f"ReflectionAPI has been initilized for {self.platform}.")

    def run(self):
        return self._ref.run()

    def register_on_message_event(self, function: Callable):
        return self._ref.register_on_message_event(function)

    def register_slash_command(self, name: str, function: Callable, description: str | None = None):
        return self._ref.register_slash_command(name, function, description)

    def get_guild_info(self, guild) -> dict:
        return self._ref.get_guild_info(guild)

    def get_thread_info(self, thread) -> dict:
        return self._ref.get_thread_info(thread)

    def get_realtime_data(self, message: ReflectionMessageBase) -> dict:
        data = dict(
            platform=self.platform,
            chat_info=message.get_chat_info()
        )

        if guild_info := self.get_guild_info(message):
            data["guild_info"] = guild_info

        if thread_info := self.get_thread_info(message):
            data["thread_info"] = thread_info

        return data

    def can_read_history(self, channel) -> bool:
        return self._ref.can_read_history(channel)

    def __typecheck_reflectionmessage(self, message: ReflectionMessageBase):
        assert self.reflection_message_cls is not None
        assert isinstance(message, self.reflection_message_cls)

    def is_message_from_the_bot(self, message: ReflectionMessageBase) -> bool:
        self.__typecheck_reflectionmessage(message)
        return self._ref.is_message_from_the_bot(message)  # pyright: ignore[reportArgumentType]

    def is_bot_mentioned(self, message: ReflectionMessageBase) -> bool:
        self.__typecheck_reflectionmessage(message)
        return self._ref.is_bot_mentioned(message)  # pyright: ignore[reportArgumentType]

    async def is_dm_or_admin(self, message: ReflectionMessageBase) -> bool:
        self.__typecheck_reflectionmessage(message)
        return await self._ref.is_dm_or_admin(message)  # pyright: ignore[reportArgumentType]

    async def send_file(self, chat_id: int, filepath: str, filename: str, caption: str | None = None):
        return await self._ref.send_file(chat_id, filepath, filename, caption)  # pyright: ignore[reportArgumentType]

    async def get_user_avatar(self, user_id: int) -> MediaCache | None:
        return await self._ref.get_user_avatar(user_id)

    async def fetch_channel_history(self, channel_id: int, n: int = 10):
        return await self._ref.fetch_channel_history(channel_id, n)  # pyright: ignore[reportArgumentType]
