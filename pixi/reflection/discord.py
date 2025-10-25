import logging
import asyncio
import os
from typing import IO, Callable

import aiohttp

import discord
from discord import app_commands

from ..caching import ImageCache, AudioCache, UnsupportedMediaException

from ..enums import Platform


class DiscordReflectionAPI:
    def __init__(self):
        self.platform = Platform.DISCORD

        self.token = os.getenv("DISCORD_BOT_TOKEN")
        if self.token is None:
            logging.warning("DISCORD_BOT_TOKEN environment variable is not set, unable to initialize discord bot.")
            return

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

    def register_on_message_event(self, function: Callable):
        @self.bot.event
        async def on_message(message):
            if asyncio.iscoroutinefunction(function):
                return await function(message)
            else:
                return function(message)
    
    def register_slash_command(self, name: str, function: Callable, description: str | None = None):
        @self.bot.tree.command(name=name, description=description) # pyright: ignore[reportArgumentType]
        async def slash_command(interaction: discord.Interaction):
            await function(interaction)
    
    def get_identifier_from_message(self, message: discord.Message | discord.Interaction) -> str:
        channel = message.channel
        assert channel is not None, "chanel is None"

        # Check if the message is in a guild (server)
        if channel.guild is not None:
            # Use the guild ID as the unique identifier
            return f"guild#{channel.guild.id}"

        # If the message is in a DM or group chat, use the channel ID
        return f"channel#{channel.id}"

    def get_message_channel_id(self, message: discord.Message) -> int:
        return message.channel.id
    
    def get_channel_info(self, message: discord.Message) -> dict:
        match message.channel.type:
            case discord.ChannelType.private:
                channel_info = {"type": "DM / Private Chat", "id": message.channel.id}
            case discord.ChannelType.group:
                channel_info = {"type": "Group Chat", "id": message.channel.id}
            case discord.ChannelType.text:
                channle_name = getattr(message.channel, 'name', "Unknown")
                channel_info = {"type": "Text", "name": channle_name, "id": message.channel.id}
            case _:
                channle_name = getattr(message.channel, 'name', "Unknown")
                channel_info = {"type": "Unknown", "name": channle_name, "id": message.channel.id}
        return channel_info

    def get_guild_info(self, guild: discord.Guild) -> dict:
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

    def get_thread_info(self, thread: discord.Thread) -> dict:
        return {
            "name": thread.name,
            "members_count": thread.member_count,
            "members": [{
                "id": m.id,
            } for m in thread.members]
        }

    def get_realtime_data(self, message: discord.Message) -> dict:
        rt_data = dict(
            platform="Discord",
            current_channel_info=self.get_channel_info(message)
        )

        if message.guild is not None:
            rt_data.update(guild=self.get_guild_info(message.guild))

        if message.thread is not None:
            rt_data.update(thread=self.get_thread_info(message.thread))

        return rt_data

    async def send_status_typing(self, message: discord.Message):
        try:
            await message.channel.typing()
        except aiohttp.ServerDisconnectedError:
            logging.exception("unable to send typing status")

    def can_read_history(self, channel) -> bool:
        # Check if the bot can read message history in the channel
        if hasattr(channel, 'permissions_for'):
            perms = channel.permissions_for(channel.guild.me) if channel.guild else None
            if perms and not perms.read_message_history:
                return False
        return True

    async def send_response(self, origin: discord.Message | discord.Interaction, text: str, ephemeral: bool = False, *args, **kwargs) -> discord.Message | discord.InteractionMessage:
        if isinstance(origin, discord.Message):
            return await origin.channel.send(text, *args, **kwargs)
        elif isinstance(origin, discord.Interaction):
            return (await origin.response.send_message(text, *args, ephemeral=ephemeral, **kwargs)).resource # pyright: ignore[reportReturnType]
        else:
            raise TypeError(f"expected `origin` to be an instance of discord.Message or discord.Interaction, but got {type(origin)}")

    async def send_reply(self, message: discord.Message | discord.Interaction, text: str, delay: int | None = None, ephemeral: bool = False, should_reply: bool = True) -> discord.Message | discord.InteractionMessage:
        if isinstance(message, discord.Message):
            # delay adds realism
            if delay is not None and delay > 0:
                async with message.channel.typing():
                    await asyncio.sleep(delay)

        num_retries = 5
        for i in range(num_retries):
            try:
                if isinstance(message, discord.Interaction):
                    return await self.send_response(message, text, ephemeral=ephemeral)
                else:
                    if (not should_reply) or (message.channel.type == discord.ChannelType.private):
                        return await self.send_response(message, text)
                    else:
                        if self.can_read_history(message.channel):
                            return await self.send_response(message, text, reference=message.to_reference(fail_if_not_exists=False))
                        else:
                            return await self.send_response(message, f"{message.author.mention} {text}")
            except discord.Forbidden as e:
                logging.exception(f"Forbidden")
                channel_id = message.channel.id if message.channel else None
                raise RuntimeError(f"Cannot send message in channel ({channel_id=})")
            except discord.HTTPException as e:
                logging.warning(f"HTTPException while sending message: {e}, retrying ({i}/{num_retries})")
        else:
            channel_id = message.channel.id if message.channel else None
            raise RuntimeError(f"There was an unexpected error while send a message in channel ({channel_id=})")

    async def edit_message(self, message: discord.Message | discord.InteractionMessage, text: str):
        await message.edit(content = text)

    def get_sender_id(self, message: discord.Message):
        return message.author.id

    def get_sender_name(self, message: discord.Message):
        return message.author.display_name

    def get_sender_information(self, message: discord.Message):
        user = message.author
        return dict(
            id=user.id,
            display_name=user.display_name,
            mention_string=user.mention,
        )

    def is_message_from_the_bot(self, message: discord.Message) -> bool:
        bot_user = message._state.user
        assert bot_user is not None, "bot_user is None"
        return message.author.id == bot_user.id

    async def fetch_attachment_images(self, message: discord.Message) -> list[ImageCache]:
        supported_mime_types = {'image/jpeg', 'image/png', 'image/webp'}
        attachments = []
        for attachment in message.attachments:
            if attachment.content_type in supported_mime_types:
                attachments.append(ImageCache(await attachment.read()))
        return attachments

    async def fetch_attachment_audio(self, message: discord.Message) -> list[AudioCache]:
        supported_mime_types = {'audio/mp3', 'audio/aac', 'audio/ogg', 'audio/flac', 'audio/opus'}
        supported_extensions = {'.mp3', '.aac', '.ogg', ".flac", ".opus", ".wav", ".webm", ".m4a"}
        attachments = []
        for attachment in message.attachments:
            mime = attachment.content_type
            ext = attachment.filename.lower().rsplit('.', 1)[-1] if '.' in attachment.filename else ''
            ext = f'.{ext}'
            if (mime and mime in supported_mime_types) or (ext in supported_extensions):
                attachments.append(AudioCache(await attachment.read()))
        return attachments

    def get_message_text(self, message: discord.Message) -> str:
        return message.content if message.content else ''

    async def fetch_message_reply(self, message: discord.Message) -> discord.Message | None:
        ref = message.reference
        if ref is None:
            return
        if ref.cached_message:
            return ref.cached_message
        if ref.message_id is None:
            return
        return await message.channel.fetch_message(ref.message_id)

    def is_bot_mentioned(self, message: discord.Message) -> bool:
        bot_user = message._state.user
        return bot_user is not None and bot_user in message.mentions

    def is_inside_dm(self, message: discord.Message) -> bool:
        return message.channel.type == discord.ChannelType.private

    async def is_dm_or_admin(self, interaction: discord.Interaction) -> bool:
        if isinstance(interaction.channel, discord.DMChannel):
            return True
        # check if user has admin permissions to use the bot commands
        if hasattr(interaction.user, 'guild_permissions') and interaction.user.guild_permissions.administrator:  # type: ignore
            return True
        return False

    async def add_reaction(self, message: discord.Message, emoji: str):
        try:
            await message.add_reaction(emoji)
        except discord.errors.NotFound:
            logging.exception("unable to add reaction, message not found.")
        except discord.Forbidden:
            logging.exception("unable to add reaction, operation forbidden.")
        except Exception:
            logging.exception("unknown error while adding a reaction to a message")

    async def send_video(self, message: discord.Message, video: IO[bytes], filename: str, caption: str | None = None):
        try:
            await message.channel.send(file=discord.File(fp=video, filename=filename, caption = caption))  # type: ignore
        except discord.Forbidden:
            logging.exception("unable to send video, operation forbidden.")
        except discord.HTTPException as e:
            logging.exception(f"HTTPException while sending video: {e}")
        except Exception:
            logging.exception("unknown error while sending a video")

    async def send_file(self, message: discord.Message, filepath: str, filename: str, caption: str | None = None):
        try:
            with open(filepath, "rb") as f:
                await message.channel.send(
                    content=caption,
                    file=discord.File(fp=f, filename=filename)
                )
        except discord.Forbidden:
            logging.exception("unable to send file, operation forbidden.")
        except discord.HTTPException as e:
            logging.exception(f"HTTPException while sending file: {e}")
        except Exception:
            logging.exception("unknown error while sending a file")
    
    async def get_user_avatar(self, user_id: int) -> ImageCache | None:
        """
        Fetches the avatar of a user and returns it as an ImageCache object.
        """
        try:
            user = await self.bot.fetch_user(user_id)
            if user is None or user.avatar is None:
                raise UnsupportedMediaException("User avatar not found or unsupported media type.")
            avatar_bytes = await user.avatar.read()
            return ImageCache(avatar_bytes)
        except discord.NotFound:
            logging.error(f"User with ID {user_id} not found.")
            return None
        except discord.HTTPException as e:
            logging.error(f"Failed to fetch user avatar: {e}")
            return None

    async def fetch_channel_history(self, channel_id: int, n: int = 10):
        channel = await self.bot.fetch_channel(channel_id)
        messages = []
        # TODO: check channel type
        async for message in channel.history(limit=int(n)):  # type: ignore
            messages.append(dict(
                from_user=self.get_sender_information(message).get("display_name", "Unknown"),
                message_text=self.get_message_text(message)
            ))

        return messages[::-1]