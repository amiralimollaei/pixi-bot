from dataclasses import asdict
import logging
import asyncio
import os
from typing import IO, Any, Callable

import discord
from discord import app_commands

from .message.discord import DiscordReflectionMessage

from ..caching.base import MediaCache, UnsupportedMediaException
from ..enums import Platform

ImageCache = None
try:
    from ..caching import ImageCache
except ImportError:
    pass


class DiscordReflectionAPI:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.platform = Platform.DISCORD

        self.token = os.getenv("DISCORD_BOT_TOKEN")
        if self.token is None:
            raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set, unable to initialize discord bot.")

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

    def run(self):
        assert self.token
        self.bot.run(self.token, log_handler=None)

    def register_on_message_event(self, function: Callable[[DiscordReflectionMessage], Any]):
        @self.bot.event
        async def on_message(message):
            message = DiscordReflectionMessage.from_origin(message)
            if asyncio.iscoroutinefunction(function):
                return await function(message)
            else:
                return function(message)

    def register_slash_command(self, name: str, function: Callable, description: str | None = None):
        @self.bot.tree.command(name=name, description=description)  # pyright: ignore[reportArgumentType]
        async def slash_command(interaction: discord.Interaction):
            message = DiscordReflectionMessage.from_origin(interaction)
            await function(message)

    def get_guild_info(self, message: DiscordReflectionMessage) -> dict:
        guild: discord.Guild | None = message.origin.guild
        if guild is None:
            return dict()
        return {
            "name": guild.name,
            "members_count": guild.member_count,
            "categories": [{
                "name": cat.name,
                "is_nsfw": cat.nsfw,
                "stage_channels": [{
                    "name": c.name,
                    "mention_string": c.mention,
                    "is_nsfw": c.nsfw,
                    "user_limit": c.user_limit,
                    "connected_listeners": {
                        "count": len(c.listeners),
                        "members": [m.display_name for m in c.listeners]
                    },
                } for c in cat.stage_channels],
                "voice_channels": [{
                    "name": c.name,
                    "mention_string": c.mention,
                    "is_nsfw": c.nsfw,
                    "user_limit": c.user_limit,
                    "connected_members": {
                        "count": len(c.members),
                        "members": [m.display_name for m in c.members]
                    },
                } for c in cat.voice_channels],
                "text_channels": [{
                    "name": c.name,
                    "mention_string": c.mention,
                    "is_nsfw": c.nsfw,
                } for c in cat.text_channels],
            } for cat in guild.categories],
            "members": [{
                "display_name": m.display_name,
                "mention_string": m.mention,
                "roles": [
                    {
                        "name": r.name,
                        "color": '#{:06X}'.format(r.color.value),
                        "created_at": r.created_at.strftime("%d/%m/%Y at %H:%M:%S")
                    } for r in m.roles
                ],
            } for m in guild.members]
        }

    def get_thread_info(self, message: DiscordReflectionMessage) -> dict:
        origin: discord.Message | discord.Interaction = message.origin
        if isinstance(origin, discord.Interaction):
            return dict()
        thread: discord.Thread | None = origin.thread
        if thread is None:
            return dict()
        return {
            "name": thread.name,
            "members_count": thread.member_count,
            "members": [{
                "id": m.id,
            } for m in thread.members]
        }

    def can_read_history(self, chat_id: int) -> bool:
        channel = self.bot.get_channel(chat_id)
        # Check if the bot can read message history in the channel
        if channel is not None and hasattr(channel, 'permissions_for') and hasattr(channel, 'guild'):
            perms = None
            if channel.guild:  # pyright: ignore[reportAttributeAccessIssue]
                perms = channel.permissions_for(channel.guild.me)  # pyright: ignore[reportAttributeAccessIssue]
            if perms and not perms.read_message_history:
                return False
        return True

    def is_message_from_the_bot(self, message: DiscordReflectionMessage) -> bool:
        bot_user = self.bot.user
        assert bot_user is not None, "bot_user is None"
        return message.author.id == bot_user.id

    def is_bot_mentioned(self, message: DiscordReflectionMessage) -> bool:
        origin: discord.Message | discord.Interaction = message.origin
        if isinstance(origin, discord.Interaction):
            return False
        bot_user = self.bot.user
        return bot_user is not None and bot_user in origin.mentions

    async def is_dm_or_admin(self, message: DiscordReflectionMessage) -> bool:
        origin: discord.Message | discord.Interaction = message.origin
        if isinstance(origin.channel, discord.DMChannel):
            return True
        # check if user has admin permissions to use the bot commands
        if hasattr(origin.user, 'guild_permissions') and origin.user.guild_permissions.administrator:  # type: ignore
            return True
        return False

    async def send_video(self, chat_id: int, video: IO[bytes], filename: str, caption: str | None = None):
        channel = self.bot.get_channel(chat_id)
        assert channel is not None
        try:
            await channel.send(file=discord.File(fp=video, filename=filename, caption=caption))  # type: ignore
        except discord.Forbidden:
            self.logger.exception("unable to send video, operation forbidden.")
        except discord.HTTPException as e:
            self.logger.exception(f"HTTPException while sending video: {e}")
        except Exception:
            self.logger.exception("unknown error while sending a video")

    async def send_file(self, chat_id: int, filepath: str, filename: str, caption: str | None = None):
        channel = self.bot.get_channel(chat_id)
        assert channel is not None
        try:
            with open(filepath, "rb") as f:
                await channel.send(  # pyright: ignore[reportAttributeAccessIssue]
                    content=caption,
                    file=discord.File(fp=f, filename=filename)
                )
        except discord.Forbidden:
            self.logger.exception("unable to send file, operation forbidden.")
        except discord.HTTPException as e:
            self.logger.exception(f"HTTPException while sending file: {e}")
        except Exception:
            self.logger.exception("unknown error while sending a file")

    async def get_user_avatar(self, user_id: int) -> MediaCache | None:
        """
        Fetches the avatar of a user and returns it as an ImageCache object.
        """
        try:
            user = await self.bot.fetch_user(user_id)
            if user is None or user.avatar is None:
                raise UnsupportedMediaException("User avatar not found or has an unsupported media type.")
            assert ImageCache
            avatar_bytes = await user.avatar.read()
            return ImageCache(avatar_bytes)
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
            message = DiscordReflectionMessage.from_origin(message)
            messages.append(dict(
                from_user=message.author.display_name or "unknown",
                message_text=message.content,
            ))

        return messages[::-1]
