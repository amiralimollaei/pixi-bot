import logging
import asyncio

import telegram
from telegram.constants import ChatType, ChatAction, ChatMemberStatus

from ..enums import Platform
from ..caching import ImageCache, AudioCache, UnsupportedMediaException


class ReflectionAPI:
    def __init__(self):
        self.platform = Platform.TELEGRAM
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

    def get_realtime_data(self, message: telegram.Message):
        return {
            "Platform": "Telegram",
            "Chat type": message.chat.type,
            "Chat title": message.chat.title
        }

    async def send_status_typing(self, message: telegram.Message):
        await message.chat.send_chat_action(ChatAction.TYPING)

    def can_read_history(self, channel) -> bool:
        return True

    async def send_response(self, origin: telegram.Message, text: str, ephemeral: bool = False, *args, **kwargs):
        try:
            await origin.reply_markdown_v2(text, *args, **kwargs)
        except telegram.error.BadRequest:
            await origin.reply_text(text, *args, **kwargs)

    async def send_reply(self, message: telegram.Message, text: str, delay: int = None, ephemeral: bool = False):
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
        return message.from_user.id

    def get_sender_name(self, message: telegram.Message):
        return message.from_user.full_name

    def get_sender_information(self, message: telegram.Message):
        user = message.from_user
        return dict(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            mention_string="@" + user.username,
        )

    def is_message_from_the_bot(self, message: telegram.Message) -> bool:
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

    async def fetch_message_reply(self, message: telegram.Message) -> telegram.Message:
        return message.reply_to_message

    def is_bot_mentioned(self, message: telegram.Message):
        username = message.get_bot().username
        return f"@{username}" in self.get_message_text(message)

    def is_inside_dm(self, message: telegram.Message) -> bool:
        return message.chat.type == ChatType.PRIVATE

    async def is_dm_or_admin(self, interaction: telegram.Message) -> bool:
        if interaction.chat.type == ChatType.PRIVATE:
            return True
        # Check if user has admin permissions to use the bot commands
        member = await interaction.get_bot().get_chat_member(interaction.chat.id, interaction.from_user.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)

    async def add_reaction(self, message: telegram.Message, emoji: str):
        await message.set_reaction(emoji)