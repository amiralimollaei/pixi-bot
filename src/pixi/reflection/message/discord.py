import logging
import discord

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


class DiscordReflectionMessage(ReflectionMessageBase):
    origin: discord.Message | discord.Interaction

    @classmethod
    def from_origin(cls, message: discord.Message | discord.Interaction) -> 'DiscordReflectionMessage':
        user = None
        content = ""
        if isinstance(message, discord.Message):
            user = message.author
            content = message.content if message.content else ""
        elif isinstance(message, discord.Interaction):
            user = message.user
        assert user is not None
        channel = message.channel
        chat_title = ""
        if channel and hasattr(channel, "name"):
            chat_title = (channel.name or "")  # pyright: ignore[reportAttributeAccessIssue]
        chat_type = ChatType.UNKNOWN
        match channel.type if channel else None:
            case discord.ChannelType.private:
                chat_type = ChatType.PRIVATE
            case discord.ChannelType.group:
                chat_type = ChatType.GROUP
            case discord.ChannelType.text:
                chat_type = ChatType.TEXT

        environment = ReflectionEnvironment(
            chat_id=channel.id if channel else -1,
            chat_title=chat_title,
            chat_type=chat_type,
            forum_id=message.guild.id if message.guild else -1,
            is_forum=message.guild is not None
        )
        return DiscordReflectionMessage(
            content=content,
            author=ReflectionMessageAuthor(
                id=user.id,
                first_name=user.name,
                last_name="",
                display_name=user.display_name,
                mention=user.mention,
            ),
            id=message.id,
            environment=environment,
            platform=Platform.DISCORD,
            origin=message
        )

    async def send(self, content: str) -> 'DiscordReflectionMessage':
        if isinstance(self.origin, discord.Message):
            return self.from_origin(await self.origin.channel.send(content))
        elif isinstance(self.origin, discord.Interaction):
            await self.origin.response.send_message(content)
            return self.from_origin(await self.origin.original_response())
        else:
            raise TypeError(f"unknown origin of type {type(self.origin)}")

    async def edit(self, content: str) -> 'DiscordReflectionMessage':
        if isinstance(self.origin, discord.Message):
            return self.from_origin(await self.origin.edit(content=content))
        elif isinstance(self.origin, discord.Interaction):
            await self.origin.response.edit_message(content=content)
            return self.from_origin(await self.origin.original_response())
        else:
            raise TypeError(f"unknown origin of type {type(self.origin)}")

    async def delete(self):
        if isinstance(self.origin, discord.Message):
            await self.origin.delete()
        elif isinstance(self.origin, discord.Interaction):
            origin = await self.origin.original_response()
            await origin.delete()
        else:
            raise TypeError(f"unknown origin of type {type(self.origin)}")

    async def typing(self):
        channel = self.origin.channel
        if channel and hasattr(channel, "typing"):
            return await channel.typing()  # pyright: ignore[reportAttributeAccessIssue]

    async def fetch_images(self) -> list[MediaCache]:
        if isinstance(self.origin, discord.Interaction):
            return []

        supported_mime_types = {'image/jpeg', 'image/png', 'image/webp'}
        attachments = []
        for attachment in self.origin.attachments:
            if attachment.content_type in supported_mime_types:
                assert ImageCache
                attachments.append(ImageCache(await attachment.read()))
        return attachments

    async def fetch_audio(self) -> list[MediaCache]:
        if isinstance(self.origin, discord.Interaction):
            return []

        supported_mime_types = {'audio/mp3', 'audio/aac', 'audio/ogg', 'audio/flac', 'audio/opus'}
        supported_extensions = {'.mp3', '.aac', '.ogg', ".flac", ".opus", ".wav", ".webm", ".m4a"}
        attachments = []
        for attachment in self.origin.attachments:
            mime = attachment.content_type
            ext = attachment.filename.lower().rsplit('.', 1)[-1] if '.' in attachment.filename else ''
            ext = f'.{ext}'
            if (mime and mime in supported_mime_types) or (ext in supported_extensions):
                assert AudioCache
                attachments.append(AudioCache(await attachment.read()))
        return attachments

    async def fetch_refrences(self) -> 'DiscordReflectionMessage | None':
        origin: discord.Message | discord.Interaction = self.origin
        if isinstance(origin, discord.Interaction):
            return
        ref = origin.reference
        if ref is None:
            return
        if ref.cached_message:
            return DiscordReflectionMessage.from_origin(ref.cached_message)
        if ref.message_id is None:
            return
        return DiscordReflectionMessage.from_origin(await origin.channel.fetch_message(ref.message_id))

    async def add_reaction(self, emoji: str):
        origin: discord.Message | discord.Interaction = self.origin
        if isinstance(origin, discord.Interaction):
            return
        try:
            await origin.add_reaction(emoji)
        except discord.errors.NotFound:
            logging.exception("unable to add reaction, message not found.")
        except discord.Forbidden:
            logging.exception("unable to add reaction, operation forbidden.")
        except Exception:
            logging.exception("unknown error while adding a reaction to a message")

    async def send_file(self, filepath: str, filename: str, caption: str | None = None):
        try:
            channel = self.origin.channel
            if channel and hasattr(channel, "send"):
                with open(filepath, "rb") as f:
                    await channel.send(  # pyright: ignore[reportAttributeAccessIssue]
                        content=caption,
                        file=discord.File(fp=f, filename=filename)
                    )
        except discord.Forbidden:
            logging.exception("unable to send file, operation forbidden.")
        except discord.HTTPException as e:
            logging.exception(f"HTTPException while sending file: {e}")
        except Exception:
            logging.exception("unknown error while sending a file")
