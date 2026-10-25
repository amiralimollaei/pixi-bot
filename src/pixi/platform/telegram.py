import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Callable

import telegram
from telegram.constants import ChatAction, ChatMemberStatus
from telegram.constants import ChatType as TChatType
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from ..caching import MediaCacheProvider
from ..model.enums import ChatType, Messages, Platform
from ..model.platform import PlatformEnvironment, PlatformMessageAuthor
from ..interfaces.platform import PlatformMessage, PlatformProvider


@dataclass(frozen=True)
class TelegramMessage(PlatformMessage):
    content: str | None
    author: PlatformMessageAuthor
    id: int
    environment: PlatformEnvironment
    platform: Platform
    origin: telegram.Message
    media_cache: MediaCacheProvider | None = None

    @classmethod
    def from_origin(
        cls,
        message: telegram.Message,
        *,
        media_cache: MediaCacheProvider | None = None,
    ) -> 'TelegramMessage':
        user = message.from_user
        assert user is not None
        content = message.text_markdown_v2 or message.caption_markdown_v2
        chat = message.chat
        chat_type = chat_type = ChatType.UNKNOWN
        match chat.type:
            case TChatType.PRIVATE:
                chat_type = ChatType.PRIVATE
            case TChatType.GROUP:
                chat_type = ChatType.GROUP
            case TChatType.SUPERGROUP:
                chat_type = ChatType.GROUP
            case TChatType.CHANNEL:
                chat_type = ChatType.TEXT
        return TelegramMessage(
            content=content,
            author=PlatformMessageAuthor(
                id=user.id,
                first_name=user.first_name,
                last_name=user.last_name or "",
                display_name=user.name,
                mention=f"@{user.username}",
            ),
            id=message.id,
            environment=PlatformEnvironment(
                chat_id=chat.id,
                chat_title=chat.title or "",
                chat_type=chat_type,
                forum_id=-1,
                is_forum=False,
            ),
            platform=Platform.TELEGRAM,
            origin=message,
            media_cache=media_cache,
        )

    async def send(self, content: str) -> 'TelegramMessage':
        return self.from_origin(await self.origin.chat.send_message(content), media_cache=self.media_cache)

    async def edit(self, content: str) -> 'TelegramMessage | None':
        new_origin = await self.origin.edit_text(text=content)
        if isinstance(new_origin, telegram.Message):
            return self.from_origin(new_origin, media_cache=self.media_cache)
        return None

    async def delete(self):
        await self.origin.delete()

    async def typing(self):
        await self.origin.chat.send_chat_action(ChatAction.TYPING)

    async def fetch_images(self) -> list[bytes]:
        if self.media_cache is None:
            return []
        origin = self.origin

        supported_image_types = {'image/jpeg', 'image/png', 'image/webp'}
        attachments = []
        # Telegram sends images as 'photo' (list of sizes) or as 'document' (if sent as file)
        image_bytes = None
        if origin.photo:
            # Get the highest resolution photo
            photo = origin.photo[-1]
            file = await photo.get_file()
            image_bytes = await file.download_as_bytearray()
        elif origin.document and origin.document.mime_type and origin.document.mime_type in supported_image_types:
            file = await origin.document.get_file()
            image_bytes = await file.download_as_bytearray()
        if image_bytes:
            attachments.append(self.media_cache.cache_image(bytes(image_bytes)))
        return attachments

    async def fetch_audio(self) -> list[bytes]:
        if self.media_cache is None:
            return []
        origin = self.origin

        supported_mime_types = {'audio/mp3', 'audio/aac', 'audio/ogg', 'audio/flac', 'audio/opus'}
        supported_extensions = {'.mp3', '.aac', '.ogg', ".flac", ".opus", ".wav", ".webm", ".m4a"}
        attachments = []
        audio_bytes = None
        if origin.audio and origin.audio.mime_type in supported_mime_types:
            file = await origin.audio.get_file()
            audio_bytes = await file.download_as_bytearray()
        elif (
            origin.document
            and origin.document.mime_type
            and origin.document.mime_type in supported_mime_types
        ):
            file = await origin.document.get_file()
            audio_bytes = await file.download_as_bytearray()
        elif (
            origin.document
            and origin.document.file_name
            and any(origin.document.file_name.lower().endswith(ext) for ext in supported_extensions)
        ):
            file = await origin.document.get_file()
            audio_bytes = await file.download_as_bytearray()
        if audio_bytes:
            attachments.append(self.media_cache.cache_audio(bytes(audio_bytes)))
        return attachments

    async def fetch_reference(self) -> 'TelegramMessage | None':
        ref = self.origin.reply_to_message
        return TelegramMessage.from_origin(ref, media_cache=self.media_cache) if ref else None

    async def add_reaction(self, emoji: str):
        await self.origin.set_reaction(emoji)

    async def send_file(self, filepath: str, filename: str, caption: str | None = None):
        for i in range(3):
            try:
                with open(filepath, "rb") as f:
                    await self.origin.chat.send_document(
                        document=f,
                        filename=filename,
                        caption=caption,
                        read_timeout=30,
                        write_timeout=600,
                    )
            except telegram.error.TimedOut as e:
                logging.error(f"Timed out while sending file: {e}, retrying {i+1}/{3}")
            except telegram.error.BadRequest as e:
                logging.exception(f"BadRequest error while sending file: {e}")
                break
            except Exception as e:
                logging.exception(f"Unexpected error while sending file: {e}")
            else:
                break


class TelegramProvider(PlatformProvider):
    def __init__(self, *, media_cache: MediaCacheProvider | None = None):
        self.media_cache = media_cache
        self.logger = logging.getLogger(self.__class__.__name__)

        self.platform = Platform.TELEGRAM
        self._ready = asyncio.Event()

        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if self.token is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set, unable to initialize telegram bot.")

        application = Application.builder() \
            .token(self.token) \
            .read_timeout(30) \
            .write_timeout(30) \
            .build()
        self.application = application
        self.known_chats: set[int] = set()

    async def start_async(self):
        """Start the Telegram bot asynchronously."""
        await self.application.initialize()
        await self.application.start()

        updater = self.application.updater
        assert updater is not None
        await updater.start_polling()

        # TODO: here we just assume that the bot is ready after starting the updater,
        # but we should ideally check if the bot is actually connected and ready to receive messages.
        self._ready.set()
        await asyncio.Future()  # Remain alive until cancelled.

    async def close_async(self):
        """Close the Telegram bot asynchronously."""
        self._ready.clear()

        updater = self.application.updater
        if updater is not None and updater.running:
            await updater.stop()

        if self.application.running:
            await self.application.stop()

        await self.application.shutdown()

    async def wait_until_ready(self):
        """Wait until the bot is fully connected and ready."""
        if self.application.bot:
            await self._ready.wait()

    def run(self):
        """Run the Telegram bot (blocking)."""
        self.application.run_polling()

    def register_on_message_event(self, function: Callable):
        async def on_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_chat:
                self.known_chats.add(update.effective_chat.id)
            message = update.message
            assert message is not None
            message = TelegramMessage.from_origin(message, media_cache=self.media_cache)
            if message is not None:
                if asyncio.iscoroutinefunction(function):
                    return await function(message)
                else:
                    return function(message)

        # Commands share the default handler group; never let this catch-all
        # shadow commands registered later by bootstrap or addons.
        self.application.add_handler(MessageHandler(
            (filters.TEXT | filters.VIDEO | filters.AUDIO | filters.Document.ALL) & ~filters.COMMAND,
            callback=on_message
        ))

    def register_slash_command(self, name: str, function: Callable, description: str | None = None):
        async def slash_command(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            assert message is not None
            message = TelegramMessage.from_origin(message, media_cache=self.media_cache)
            if message is not None:
                if asyncio.iscoroutinefunction(function):
                    return await function(message)
                else:
                    return function(message)
        self.application.add_handler(CommandHandler(name, slash_command))

    def get_guild_info(self, message: PlatformMessage) -> dict:
        return dict()

    def get_thread_info(self, message: PlatformMessage) -> dict:
        return dict()

    def can_read_history(self, chat_id: int) -> bool:
        return True

    def is_message_from_the_bot(self, message: PlatformMessage) -> bool:
        assert isinstance(message, TelegramMessage)
        origin: telegram.Message = message.origin
        assert origin.from_user is not None, "from_user is None"
        return origin.get_bot().id == origin.from_user.id

    def is_bot_mentioned(self, message: PlatformMessage) -> bool:
        assert isinstance(message, TelegramMessage)
        reply_message = message.origin.reply_to_message
        if reply_message is not None and reply_message.from_user is not None and self.application.bot.id == reply_message.from_user.id:
            return True
        return message.content is not None and f"@{self.application.bot.username}" in message.content

    async def is_dm_or_admin(self, message: PlatformMessage) -> bool:
        assert isinstance(message, TelegramMessage)
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

    async def get_user_avatar(self, user_id: int) -> bytes | None:
        if self.media_cache is None:
            return None
        try:
            file = await self.application.bot.get_user_profile_photos(user_id)
            if file.photos:
                photo = file.photos[0][-1]  # Get the highest resolution photo
                image_bytes = await (await photo.get_file()).download_as_bytearray()
                return self.media_cache.cache_image(bytes(image_bytes))
        except telegram.error.BadRequest as e:
            self.logger.error(f"Failed to fetch user avatar: {e}")
            return None
        except Exception as e:
            self.logger.exception(f"Unexpected error while fetching user avatar: {e}")
            return None

    async def fetch_channel_history(self, channel_id: int, n: int = 10):
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("fetch_channel_history", self.platform))
