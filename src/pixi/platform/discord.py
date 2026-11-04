import asyncio
import logging
import os
from dataclasses import dataclass
from io import BufferedIOBase
from typing import IO, Any, Callable, cast

import discord
from discord import app_commands

from pixi.caching import MediaCacheProvider, UnsupportedMediaException
from pixi.interfaces.platform import PlatformMessage, PlatformProvider
from pixi.model.enums import ChatType, Platform
from pixi.model.platform import PlatformEnvironment, PlatformMessageAuthor


@dataclass(frozen=True)
class DiscordMessage(PlatformMessage):
    content: str | None
    author: PlatformMessageAuthor
    id: int
    environment: PlatformEnvironment
    platform: Platform
    origin: discord.Message | discord.Interaction
    media_cache: MediaCacheProvider | None = None

    @classmethod
    def from_origin(
        cls,
        message: discord.Message | discord.Interaction,
        *,
        media_cache: MediaCacheProvider | None = None,
    ) -> "DiscordMessage":
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
            chat_title = channel.name or ""  # pyright: ignore[reportAttributeAccessIssue]
        chat_type = ChatType.UNKNOWN
        match channel.type if channel else None:
            case discord.ChannelType.private:
                chat_type = ChatType.PRIVATE
            case discord.ChannelType.group:
                chat_type = ChatType.GROUP
            case discord.ChannelType.text:
                chat_type = ChatType.TEXT

        environment = PlatformEnvironment(
            chat_id=channel.id if channel else -1,
            chat_title=chat_title,
            chat_type=chat_type,
            forum_id=message.guild.id if message.guild else -1,
            is_forum=message.guild is not None,
        )
        return DiscordMessage(
            content=content,
            author=PlatformMessageAuthor(
                id=user.id,
                first_name=user.name,
                last_name="",
                display_name=user.display_name,
                mention=user.mention,
            ),
            id=message.id,
            environment=environment,
            platform=Platform.DISCORD,
            origin=message,
            media_cache=media_cache,
        )

    async def send(self, content: str) -> "DiscordMessage":
        if isinstance(self.origin, discord.Message):
            return self.from_origin(
                await self.origin.channel.send(content), media_cache=self.media_cache
            )
        elif isinstance(self.origin, discord.Interaction):
            await self.origin.response.send_message(content)
            return self.from_origin(
                await self.origin.original_response(), media_cache=self.media_cache
            )
        else:
            raise TypeError(f"unknown origin of type {type(self.origin)}")

    async def edit(self, content: str) -> "DiscordMessage":
        if isinstance(self.origin, discord.Message):
            return self.from_origin(
                await self.origin.edit(content=content), media_cache=self.media_cache
            )
        elif isinstance(self.origin, discord.Interaction):
            await self.origin.response.edit_message(content=content)
            return self.from_origin(
                await self.origin.original_response(), media_cache=self.media_cache
            )
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
            await channel.typing()  # pyright: ignore[reportAttributeAccessIssue]

    async def fetch_images(self) -> list[bytes]:
        if self.media_cache is None or isinstance(self.origin, discord.Interaction):
            return []

        supported_mime_types = {"image/jpeg", "image/png", "image/webp"}
        attachments = []
        for attachment in self.origin.attachments:
            if attachment.content_type in supported_mime_types:
                attachments.append(
                    self.media_cache.cache_image(await attachment.read())
                )
        return attachments

    async def fetch_audio(self) -> list[bytes]:
        if self.media_cache is None or isinstance(self.origin, discord.Interaction):
            return []

        supported_mime_types = {
            "audio/mp3",
            "audio/aac",
            "audio/ogg",
            "audio/flac",
            "audio/opus",
        }
        supported_extensions = {
            ".mp3",
            ".aac",
            ".ogg",
            ".flac",
            ".opus",
            ".wav",
            ".webm",
            ".m4a",
        }
        attachments = []
        for attachment in self.origin.attachments:
            mime = attachment.content_type
            ext = (
                attachment.filename.lower().rsplit(".", 1)[-1]
                if "." in attachment.filename
                else ""
            )
            ext = f".{ext}"
            if (mime and mime in supported_mime_types) or (ext in supported_extensions):
                attachments.append(
                    self.media_cache.cache_audio(await attachment.read())
                )
        return attachments

    async def fetch_reference(self) -> "DiscordMessage | None":
        origin: discord.Message | discord.Interaction = self.origin
        if isinstance(origin, discord.Interaction):
            return
        ref = origin.reference
        if ref is None:
            return
        if ref.cached_message:
            return DiscordMessage.from_origin(
                ref.cached_message, media_cache=self.media_cache
            )
        if ref.message_id is None:
            return
        return DiscordMessage.from_origin(
            await origin.channel.fetch_message(ref.message_id),
            media_cache=self.media_cache,
        )

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
                        content=caption, file=discord.File(fp=f, filename=filename)
                    )
        except discord.Forbidden:
            logging.exception("unable to send file, operation forbidden.")
        except discord.HTTPException as e:
            logging.exception(f"HTTPException while sending file: {e}")
        except Exception:
            logging.exception("unknown error while sending a file")


class DiscordProvider(PlatformProvider):
    def __init__(self, *, media_cache: MediaCacheProvider | None = None):
        self.media_cache = media_cache
        self.logger = logging.getLogger(self.__class__.__name__)

        self.platform = Platform.DISCORD

        self.token = os.getenv("DISCORD_BOT_TOKEN")
        if self.token is None:
            raise RuntimeError(
                "DISCORD_BOT_TOKEN environment variable is not set, unable to initialize discord bot."
            )

        class DiscordClient(discord.Client):
            def __init__(self, *args, **kwargs):
                intents = discord.Intents.default()
                intents.message_content = True
                intents.members = True
                super().__init__(intents=intents, *args, **kwargs)
                self.tree = app_commands.CommandTree(self)

            async def setup_hook(self):
                await self.tree.sync()

        self.bot = DiscordClient()

    async def start_async(self):
        """Start the Discord bot asynchronously."""
        assert self.token
        await self.bot.start(self.token)

    async def close_async(self):
        """Close the Discord bot asynchronously."""
        await self.bot.close()

    async def wait_until_ready(self):
        """Wait until the bot is fully connected and ready."""
        await self.bot.wait_until_ready()

    def run(self):
        """Run the Discord bot (blocking)."""
        assert self.token
        self.bot.run(self.token, log_handler=None)

    def register_on_message_event(self, function: Callable[[DiscordMessage], Any]):
        @self.bot.event
        async def on_message(message):
            message = DiscordMessage.from_origin(message, media_cache=self.media_cache)
            if asyncio.iscoroutinefunction(function):
                return await function(message)
            else:
                return function(message)

    def register_slash_command(
        self, name: str, function: Callable, description: str | None = None
    ):
        @self.bot.tree.command(name=name, description=description)  # pyright: ignore[reportArgumentType]
        async def slash_command(interaction: discord.Interaction):
            message = DiscordMessage.from_origin(
                interaction, media_cache=self.media_cache
            )
            await function(message)

    def get_guild_info(self, message: PlatformMessage) -> dict:
        assert isinstance(message, DiscordMessage)
        guild: discord.Guild | None = message.origin.guild
        if guild is None:
            return dict()
        return {
            "name": guild.name,
            "members_count": guild.member_count,
            "categories": [
                {
                    "name": cat.name,
                    "is_nsfw": cat.nsfw,
                    "stage_channels": [
                        {
                            "name": c.name,
                            "mention_string": c.mention,
                            "is_nsfw": c.nsfw,
                            "user_limit": c.user_limit,
                            # "connected_listeners": {
                            #    "count": len(c.listeners),
                            #    "members": [m.display_name for m in c.listeners]
                            # },
                        }
                        for c in cat.stage_channels
                    ],
                    "voice_channels": [
                        {
                            "name": c.name,
                            "mention_string": c.mention,
                            "is_nsfw": c.nsfw,
                            "user_limit": c.user_limit,
                            # "connected_members": {
                            #    "count": len(c.members),
                            #    "members": [m.display_name for m in c.members]
                            # },
                        }
                        for c in cat.voice_channels
                    ],
                    "text_channels": [
                        {
                            "name": c.name,
                            "mention_string": c.mention,
                            "is_nsfw": c.nsfw,
                        }
                        for c in cat.text_channels
                    ],
                }
                for cat in guild.categories
            ],
            "members": [
                {
                    "display_name": m.display_name,
                    "mention_string": m.mention,
                    "roles": [
                        {
                            "name": r.name,
                            "color": "#{:06X}".format(r.color.value),
                            #    "created_at": r.created_at.strftime("%d/%m/%Y at %H:%M:%S")
                        }
                        for r in m.roles
                    ],
                }
                for m in guild.members
            ],
        }

    def get_thread_info(self, message: PlatformMessage) -> dict:
        assert isinstance(message, DiscordMessage)
        origin: discord.Message | discord.Interaction = message.origin
        if isinstance(origin, discord.Interaction):
            return dict()
        thread: discord.Thread | None = origin.thread
        if thread is None:
            return dict()
        return {
            "name": thread.name,
            "members_count": thread.member_count,
            "members": [
                {
                    "id": m.id,
                }
                for m in thread.members
            ],
        }

    def can_read_history(self, chat_id: int) -> bool:
        channel = self.bot.get_channel(chat_id)
        # Check if the bot can read message history in the channel
        if (
            channel is not None
            and hasattr(channel, "permissions_for")
            and hasattr(channel, "guild")
        ):
            perms = None
            if channel.guild:  # pyright: ignore[reportAttributeAccessIssue]
                perms = channel.permissions_for(channel.guild.me)  # pyright: ignore[reportAttributeAccessIssue]
            if perms and not perms.read_message_history:
                return False
        return True

    def is_message_from_the_bot(self, message: PlatformMessage) -> bool:
        assert isinstance(message, DiscordMessage)
        bot_user = self.bot.user
        assert bot_user is not None, "bot_user is None"
        return message.author.id == bot_user.id

    def is_bot_mentioned(self, message: PlatformMessage) -> bool:
        assert isinstance(message, DiscordMessage)
        origin: discord.Message | discord.Interaction = message.origin
        if isinstance(origin, discord.Interaction):
            return False
        bot_user = self.bot.user
        return bot_user is not None and bot_user in origin.mentions

    async def is_dm_or_admin(self, message: PlatformMessage) -> bool:
        assert isinstance(message, DiscordMessage)
        origin: discord.Message | discord.Interaction = message.origin
        if isinstance(origin.channel, discord.DMChannel):
            return True
        # check if user has admin permissions to use the bot commands
        user = None
        if isinstance(origin, discord.Message):
            user = origin.author
        elif isinstance(origin, discord.Interaction):
            user = origin.user
        return isinstance(user, discord.Member) and user.guild_permissions.administrator

    async def send_video(
        self, chat_id: int, video: IO[bytes], filename: str, caption: str | None = None
    ):
        channel = self.bot.get_channel(chat_id)
        assert isinstance(channel, discord.abc.Messageable)
        try:
            # discord.py accepts IOBase streams but annotates only buffered ones.
            attachment = discord.File(fp=cast(BufferedIOBase, video), filename=filename)
            await channel.send(content=caption, file=attachment)
        except discord.Forbidden:
            self.logger.exception("unable to send video, operation forbidden.")
        except discord.HTTPException as e:
            self.logger.exception(f"HTTPException while sending video: {e}")
        except Exception:
            self.logger.exception("unknown error while sending a video")

    async def send_file(
        self, chat_id: int, filepath: str, filename: str, caption: str | None = None
    ):
        channel = self.bot.get_channel(chat_id)
        assert channel is not None
        try:
            with open(filepath, "rb") as f:
                await channel.send(  # pyright: ignore[reportAttributeAccessIssue]
                    content=caption, file=discord.File(fp=f, filename=filename)
                )
        except discord.Forbidden:
            self.logger.exception("unable to send file, operation forbidden.")
        except discord.HTTPException as e:
            self.logger.exception(f"HTTPException while sending file: {e}")
        except Exception:
            self.logger.exception("unknown error while sending a file")

    async def get_user_avatar(self, user_id: int) -> bytes | None:
        """
        Fetches the avatar of a user, caches it, and returns its hash.
        """
        if self.media_cache is None:
            return None
        try:
            user = await self.bot.fetch_user(user_id)
            if user is None or user.avatar is None:
                raise UnsupportedMediaException(
                    "User avatar not found or has an unsupported media type."
                )
            avatar_bytes = await user.avatar.read()
            return self.media_cache.cache_image(avatar_bytes)
        except discord.NotFound:
            self.logger.error(f"User with ID {user_id} not found.")
            return None
        except discord.HTTPException as e:
            self.logger.error(f"Failed to fetch user avatar: {e}")
            return None

    async def fetch_channel_history(self, channel_id: int, n: int = 10):
        channel = await self.bot.fetch_channel(channel_id)
        messages = []
        # TODO: check channel type
        async for message in channel.history(limit=int(n)):  # type: ignore
            message = DiscordMessage.from_origin(message, media_cache=self.media_cache)
            messages.append(
                dict(
                    from_user=message.author.display_name or "unknown",
                    message_text=message.content,
                )
            )

        return messages[::-1]
