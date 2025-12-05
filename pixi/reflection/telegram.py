import logging
import asyncio
import os
from typing import Callable

import telegram
from telegram.constants import ChatType, ChatMemberStatus
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters


from .message.telegram import TelegramReflectionMessage
from ..caching.base import MediaCache, UnsupportedMediaException
from ..enums import Platform, Messages

ImageCache = None
try:
    from ..caching import ImageCache
except ImportError:
    pass


class TelegramReflectionAPI:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.platform = Platform.TELEGRAM

        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if self.token is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set, unable to initialize telegram bot.")

        application = Application.builder() \
            .token(self.token) \
            .read_timeout(30) \
            .write_timeout(30) \
            .build()
        self.application = application

    def run(self):
        self.application.run_polling()

    def register_on_message_event(self, function: Callable):
        async def on_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            assert message is not None
            message = TelegramReflectionMessage.from_origin(message)
            if message is not None:
                if asyncio.iscoroutinefunction(function):
                    return await function(message)
                else:
                    return function(message)

        self.application.add_handler(MessageHandler(
            filters.TEXT | filters.VIDEO | filters.AUDIO | filters.Document.ALL,
            callback=on_message
        ))

    def register_slash_command(self, name: str, function: Callable, description: str | None = None):
        async def slash_command(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            assert message is not None
            message = TelegramReflectionMessage.from_origin(message)
            if message is not None:
                if asyncio.iscoroutinefunction(function):
                    return await function(message)
                else:
                    return function(message)
        self.application.add_handler(CommandHandler(name, slash_command))

    def get_guild_info(self, message: TelegramReflectionMessage) -> dict:
        return dict()

    def get_thread_info(self, message: TelegramReflectionMessage) -> dict:
        return dict()

    def can_read_history(self, channel) -> bool:
        return True

    def is_message_from_the_bot(self, message: TelegramReflectionMessage) -> bool:
        origin: telegram.Message = message.origin
        assert origin.from_user is not None, "from_user is None"
        return origin.get_bot().id == origin.from_user.id

    def is_bot_mentioned(self, message: TelegramReflectionMessage):
        return f"@{self.application.bot.username}" in message.content

    async def is_dm_or_admin(self, message: TelegramReflectionMessage) -> bool:
        if message.environment.chat_type == ChatType.PRIVATE:
            return True
        # Check if user has admin permissions to use the bot commands
        member = await self.application.bot.get_chat_member(message.environment.chat_id, message.author.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)

    async def send_file(self, chat_id: int, filepath: str, filename: str, caption: str | None = None):
        chat = await self.application.bot.get_chat(chat_id)
        for i in range(3):
            try:
                with open(filepath, "rb") as f:
                    await chat.send_document(
                        document=f,
                        filename=filename,
                        caption=caption,
                        read_timeout=30,
                        write_timeout=600,
                    )
            except telegram.error.TimedOut as e:
                self.logger.error(f"Timed out while sending file: {e}, retrying {i+1}/{3}")
            except telegram.error.BadRequest as e:
                self.logger.exception(f"BadRequest error while sending file: {e}")
                break
            except Exception as e:
                self.logger.exception(f"Unexpected error while sending file: {e}")
            else:
                break

    async def get_user_avatar(self, user_id: int) -> MediaCache | None:
        try:
            file = await self.application.bot.get_user_profile_photos(user_id)
            if file.photos:
                photo = file.photos[0][-1]  # Get the highest resolution photo
                assert ImageCache
                image_bytes = await (await photo.get_file()).download_as_bytearray()
                return ImageCache(bytes(image_bytes))
        except telegram.error.BadRequest as e:
            self.logger.error(f"Failed to fetch user avatar: {e}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error while fetching user avatar: {e}")
            return None

    async def fetch_channel_history(self, channel_id: int, n: int = 10):
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("fetch_channel_history", self.platform))
