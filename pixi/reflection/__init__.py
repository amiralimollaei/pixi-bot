import logging
from typing import IO

import aiohttp

from ..typing import Optional
from ..enums import Platform
from ..caching import ImageCache, AudioCache


class ReflectionAPI:
    class Forbidden(Exception):
        def __init__(self, msg: str, platform: Platform, *args):
            super().__init__(*args)
            self.platform = platform
            self.msg = msg

    def __init__(self, platform: Platform, bot):
        assert type(platform) == Platform
        self.platform = platform

        match platform:
            case Platform.DISCORD:
                from .discord import ReflectionAPI
                self._ref = ReflectionAPI(bot)
            case Platform.TELEGRAM:
                from .telegram import ReflectionAPI
                self._ref = ReflectionAPI(bot)

    def get_identifier_from_message(self, message) -> str:
        return self._ref.get_identifier_from_message(message)

    def get_message_channel_id(self, message) -> int:
        return self._ref.get_message_channel_id(message)

    def get_channel_info(self, message) -> dict:
        return self._ref.get_channel_info(message)

    def get_guild_info(self, guild) -> dict:
        return self._ref.get_guild_info(guild)

    def get_thread_info(self, thread) -> dict:
        return self._ref.get_thread_info(thread)

    def get_realtime_data(self, message) -> dict:
        return self._ref.get_realtime_data(message)

    async def send_status_typing(self, message):
        try:
            return await self._ref.send_status_typing(message)
        except aiohttp.ClientError:
            logging.exception("Connection error while sending status typing")

    def can_read_history(self, channel) -> bool:
        return self._ref.can_read_history(channel)

    async def send_response(self, origin, text: str, ephemeral: bool = False, *args, **kwargs):
        return await self._ref.send_response(origin, text, ephemeral, *args, **kwargs)

    async def send_reply(self, message, text: str, delay: Optional[int] = None, ephemeral: bool = False, should_reply: bool = True):
        # Hotfix: ensure the response is not too long
        return await self._ref.send_reply(message, text[:1024], delay, ephemeral, should_reply)

    def get_sender_id(self, message) -> int:
        return self._ref.get_sender_id(message)

    def get_sender_name(self, message) -> str:
        return self._ref.get_sender_name(message)

    def get_sender_information(self, message) -> dict:
        return self._ref.get_sender_information(message)

    def is_message_from_the_bot(self, message) -> bool:
        return self._ref.is_message_from_the_bot(message)

    async def fetch_attachment_images(self, message) -> list[ImageCache]:
        return await self._ref.fetch_attachment_images(message)

    async def fetch_attachment_audio(self, message) -> list[AudioCache]:
        return await self._ref.fetch_attachment_audio(message)

    def get_message_text(self, message) -> str:
        return self._ref.get_message_text(message)

    async def fetch_message_reply(self, message):
        return await self._ref.fetch_message_reply(message)

    def is_bot_mentioned(self, message) -> bool:
        return self._ref.is_bot_mentioned(message)

    def is_inside_dm(self, message) -> bool:
        return self._ref.is_inside_dm(message)

    async def is_dm_or_admin(self, origin) -> bool:
        return await self._ref.is_dm_or_admin(origin)

    async def add_reaction(self, message, emoji: str):
        return await self._ref.add_reaction(message, emoji)

    async def send_video(self, message, video: IO[bytes], filename: str, caption: str | None = None):
        return await self._ref.send_video(message, video, filename, caption)
    
    async def send_file(self, message, filepath: str, filename: str, caption: str | None = None):
        return await self._ref.send_file(message, filepath, filename, caption)

    async def get_user_avatar(self, user_id: int) -> ImageCache | None:
        return await self._ref.get_user_avatar(user_id)
