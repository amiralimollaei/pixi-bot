import logging
import asyncio
from typing import IO

import telegram
from telegram.constants import ChatType, ChatAction, ChatMemberStatus

from ..enums import Platform, Messages
from ..caching import ImageCache, AudioCache, UnsupportedMediaException


class ReflectionAPI:
    def __init__(self, bot: telegram.Bot):
        self.platform = Platform.TELEGRAM
        self.bot = bot
        logging.debug("ReflectionAPI has been initilized for TELEGRAM.")

    def get_identifier_from_message(self, message: telegram.Message) -> str:
        chat = message.chat
        match chat.type:
            case ChatType.PRIVATE:
                return f"user#{chat.id}"
            case ChatType.GROUP:
                return f"group#{chat.id}"
            case ChatType.SUPERGROUP:
                return f"group#{chat.id}"
            case ChatType.CHANNEL:
                return f"channel#{chat.id}"
            case _:
                return f"chat#{chat.id}"

    def get_message_channel_id(self, message: telegram.Message) -> int:
        return message.chat.id

    def get_channel_info(self, message: telegram.Message) -> dict:
        return {"type": message.chat.type, "name": message.chat.title, "id": message.chat.id}

    def get_guild_info(self, guild) -> dict:
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("get_guild_info", self.platform.title()))

    def get_thread_info(self, thread) -> dict:
        raise NotImplementedError(Messages.NOT_IMPLEMENTED % ("get_thread_info", self.platform.title()))

    def get_realtime_data(self, message: telegram.Message) -> dict:
        return dict(
            platform="Telegram",
            current_channel_info=self.get_channel_info(message),
        )

    async def send_status_typing(self, message: telegram.Message):
        await message.chat.send_chat_action(ChatAction.TYPING)

    def can_read_history(self, channel) -> bool:
        return True

    async def send_response(self, origin: telegram.Message, text: str, ephemeral: bool = False, *args, **kwargs):
        try:
            await origin.reply_markdown_v2(text, *args, **kwargs)
        except telegram.error.BadRequest:
            await origin.reply_text(text, *args, **kwargs)

    async def send_reply(self, message: telegram.Message, text: str, delay: int | None = None, ephemeral: bool = False, should_reply: bool = True):
        chat_id = message.chat_id

        # delay adds realism
        sleep_time = delay or 0.0
        while sleep_time > 0:
            await message.chat.send_chat_action(ChatAction.TYPING)
            await asyncio.sleep(min(2, sleep_time))
            sleep_time -= 2

        num_retries = 5
        for i in range(num_retries):
            try:
                await self.send_response(message, text)
                break
            except telegram.error.TimedOut as e:
                logging.warning(f"Timed out while sending message: {e}, retrying ({i}/{num_retries})")
            except telegram.error.Forbidden:
                logging.exception(f"Forbidden")
                raise RuntimeError(f"Cannot send message in chat {chat_id}")
        else:
            raise RuntimeError(f"There was an unexpected error while send a message in chat {chat_id}")

    def get_sender_id(self, message: telegram.Message):
        assert message.from_user is not None, "from_user is None"
        return message.from_user.id

    def get_sender_name(self, message: telegram.Message):
        assert message.from_user is not None, "from_user is None"
        return message.from_user.full_name

    def get_sender_information(self, message: telegram.Message):
        assert message.from_user is not None, "from_user is None"
        user = message.from_user
        return dict(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            mention_string=f"@{user.username}",
        )

    def is_message_from_the_bot(self, message: telegram.Message) -> bool:
        assert message.from_user is not None, "from_user is None"
        return message.get_bot().id == message.from_user.id

    async def fetch_attachment_images(self, message: telegram.Message) -> list[ImageCache]:
        supported_image_types = {'image/jpeg', 'image/png', 'image/webp'}
        attachments = []
        # Telegram sends images as 'photo' (list of sizes) or as 'document' (if sent as file)
        image_bytes = None
        if message.photo:
            # Get the highest resolution photo
            photo = message.photo[-1]
            file = await photo.get_file()
            image_bytes = await file.download_as_bytearray()
        elif message.document and message.document.mime_type and message.document.mime_type in supported_image_types:
            file = await message.document.get_file()
            image_bytes = await file.download_as_bytearray()
        if image_bytes:
            attachments.append(ImageCache(bytes(image_bytes)))
        return attachments

    async def fetch_attachment_audio(self, message: telegram.Message) -> list[AudioCache]:
        # Only allow compressed audio formats
        supported_audio_types = {'audio/mp3', 'audio/aac', 'audio/ogg'}
        supported_extensions = {'.mp3', '.aac', '.ogg'}
        attachments = []
        audio_bytes = None
        if message.audio and message.audio.mime_type in supported_audio_types:
            file = await message.audio.get_file()
            audio_bytes = await file.download_as_bytearray()
        elif (
            message.document
            and message.document.mime_type
            and message.document.mime_type in supported_audio_types
        ):
            file = await message.document.get_file()
            audio_bytes = await file.download_as_bytearray()
        elif (
            message.document
            and message.document.file_name
            and any(message.document.file_name.lower().endswith(ext) for ext in supported_extensions)
        ):
            file = await message.document.get_file()
            audio_bytes = await file.download_as_bytearray()
        if audio_bytes:
            attachments.append(AudioCache(bytes(audio_bytes)))
        return attachments

    def get_message_text(self, message: telegram.Message) -> str:
        text = message.text_markdown_v2 or message.caption_markdown_v2
        if text is None:
            text = ""
        return text

    async def fetch_message_reply(self, message: telegram.Message) -> telegram.Message | None:
        return message.reply_to_message

    def is_bot_mentioned(self, message: telegram.Message):
        username = message.get_bot().username
        return f"@{username}" in self.get_message_text(message)

    def is_inside_dm(self, message: telegram.Message) -> bool:
        return message.chat.type == ChatType.PRIVATE

    async def is_dm_or_admin(self, interaction: telegram.Message) -> bool:
        assert interaction.from_user is not None, "from_user is None"

        if interaction.chat.type == ChatType.PRIVATE:
            return True
        # Check if user has admin permissions to use the bot commands
        member = await interaction.get_bot().get_chat_member(interaction.chat.id, interaction.from_user.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)

    async def add_reaction(self, message: telegram.Message, emoji: str):
        await message.set_reaction(emoji)

    async def send_video(self, message: telegram.Message, video: IO[bytes], filename: str, caption: str | None = None):
        for i in range(3):
            try:
                return await message.chat.send_video(video, filename=filename, caption=caption)
            except telegram.error.Forbidden:
                logging.exception("unable to send video, operation forbidden.")
                return
            except telegram.error.BadRequest as e:
                logging.exception(f"BadRequest while sending video: {e}")
                return
            except telegram.error.TimedOut as e:
                logging.exception(f"Timed out while sending video: {e}, retrying {i+1}/{3}")

    async def send_file(self, message: telegram.Message, filepath: str, filename: str, caption: str | None = None):
        for i in range(3):
            try:
                with open(filepath, "rb") as f:
                    await message.chat.send_document(
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

    async def get_user_avatar(self, user_id) -> ImageCache | None:
        try:
            file = await self.bot.get_user_profile_photos(user_id)
            if file.photos:
                photo = file.photos[0][-1]  # Get the highest resolution photo
                image_bytes = await (await photo.get_file()).download_as_bytearray()
                return ImageCache(bytes(image_bytes))
        except telegram.error.BadRequest as e:
            logging.error(f"Failed to fetch user avatar: {e}")
            return None
        except Exception as e:
            logging.exception(f"Unexpected error while fetching user avatar: {e}")
            return None
