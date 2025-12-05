import logging
import telegram
from telegram.constants import ChatAction, ChatType as TChatType

from . import ReflectionMessageBase, ReflectionMessageAuthor, ReflectionEnvironment, ChatType, Platform
from ...caching.base import MediaCache

ImageCache = None
AudioCache = None
try:
    from ...caching import ImageCache
except ImportError:
    pass
try:
    from ...caching import AudioCache
except ImportError:
    pass


class TelegramReflectionMessage(ReflectionMessageBase):
    origin: telegram.Message

    @classmethod
    def from_origin(cls, message: telegram.Message) -> 'TelegramReflectionMessage':
        user = message.from_user
        assert user is not None
        content = message.text_markdown_v2
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
        return TelegramReflectionMessage(
            content=content,
            author=ReflectionMessageAuthor(
                id=user.id,
                first_name=user.first_name,
                last_name=user.last_name or "",
                display_name=user.name,
                mention=f"@{user.username}",
            ),
            id=message.id,
            environment=ReflectionEnvironment(
                chat_id=chat.id,
                chat_title=chat.title or "",
                chat_type=chat_type,
                forum_id=-1,
                is_forum=False,
            ),
            platform=Platform.TELEGRAM,
            origin=message
        )

    async def send(self, content: str) -> 'TelegramReflectionMessage':
        return self.from_origin(await self.origin.chat.send_message(content))

    async def edit(self, content: str) -> 'TelegramReflectionMessage | None':
        new_origin = await self.origin.edit_text(text=content)
        if isinstance(new_origin, telegram.Message):
            return self.from_origin(new_origin)
        return None

    async def delete(self):
        await self.origin.delete()

    async def typing(self):
        return await self.origin.chat.send_chat_action(ChatAction.TYPING)

    async def fetch_images(self) -> list[MediaCache]:
        origin: telegram.Message = self.origin

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
            assert ImageCache
            attachments.append(ImageCache(bytes(image_bytes)))
        return attachments

    async def fetch_audio(self) -> list[MediaCache]:
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
            assert AudioCache
            attachments.append(AudioCache(bytes(audio_bytes)))
        return attachments

    async def fetch_refrences(self) -> 'TelegramReflectionMessage | None':
        ref = self.origin.reply_to_message
        return TelegramReflectionMessage.from_origin(ref) if ref else None

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
