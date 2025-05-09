import logging
import asyncio

import telegram
from telegram.constants import ChatType, ChatAction, ChatMemberStatus

from enums import Platform
from ..utils import ImageCache

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
    
    async def send_reply(self, message: telegram.Message, text: str, delay: int = None):
        chat_id = message.chat_id

        # delay adds realism
        sleep_time = delay
        while sleep_time > 0:
            await message.chat.send_chat_action(ChatAction.TYPING)
            await asyncio.sleep(min(2, sleep_time))
            sleep_time -= 2
        
        num_retries = 5
        for i in range(num_retries):
            try:
                try:
                    await message.reply_markdown_v2(text)
                except telegram.error.BadRequest:
                    await message.reply_text(text)
            except telegram.error.TimedOut as e:
                logging.warning(f"HTTPException while sending message: {e}, retrying ({i}/{num_retries})")
            except telegram.error.Forbidden:
                logging.exception(f"Cannot send message in chat {chat_id}")
                raise RuntimeError(f"Cannot send message in chat {chat_id}")
            else:
                return
        raise RuntimeError(f"There was an unexpected error while send a message in chat {chat_id}")
    
    def get_sender_id(self, message: telegram.Message):
        return message.from_user.id
    
    def get_sender_name(self, message: telegram.Message):
        return message.from_user.full_name

    
    def is_message_from_the_bot(self, message: telegram.Message) -> bool:
        return message.get_bot().id == message.from_user.id
    
    async def fetch_attachment_images(self, message: telegram.Message) -> list[ImageCache]:
        supported_image_types = {'image/jpeg', 'image/png', 'image/webp'}
        attached_images = []
        # Telegram sends images as 'photo' (list of sizes) or as 'document' (if sent as file)
        if message.photo:
            # Get the highest resolution photo
            photo = message.photo[-1]
            file = await photo.get_file()
            image_bytes = await file.download_as_bytearray()
            attached_images.append(ImageCache(image_bytes=bytes(image_bytes)))
        elif message.document and message.document.mime_type and message.document.mime_type in supported_image_types:
            file = await message.document.get_file()
            image_bytes = await file.download_as_bytearray()
            attached_images.append(ImageCache(image_bytes=bytes(image_bytes)))
        return attached_images
    
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

if __name__ == "__main__":
    ReflectionAPI()