import logging
import asyncio

import discord

from ..enums import Platform
from ..utils import ImageCache


class ReflectionAPI:
    def __init__(self):
        self.platform = Platform.DISCORD
        logging.debug("ReflectionAPI has been initilized for DISCORD.")

    def get_identifier_from_message(self, message: discord.Message | discord.Interaction) -> str:
        channel = message.channel

        # Check if the message is in a guild (server)
        if channel.guild is not None:
            # Use the guild ID as the unique identifier
            return f"guild#{channel.guild.id}"

        # If the message is in a DM or group chat, use the channel ID
        return f"channel#{channel.id}"

    def get_realtime_data(self, message: discord.Message):
        rt_data = {"Platform": "Discord"}

        match message.channel.type:
            case discord.ChannelType.private:
                rt_data.update({"text_channel": {"type": "DM / Private Chat"}})
            case discord.ChannelType.group:
                rt_data.update({"text_channel": {"type": "Group Chat"}})
            case discord.ChannelType.text:
                channle_name = message.channel.name
                rt_data.update({"text_channel": {"type": "Unknown", "name": channle_name}})
            case _:
                channle_name = getattr(message.channel, 'name', "Unknown")
                rt_data.update({"text_channel": {"type": "Unknown", "name": channle_name}})
        rt_data["text_channel"].update({"id": message.channel.id})

        if message.guild is not None:
            rt_data.update({
                "guild": {
                    "name": message.guild.name,
                    "members_count": message.guild.member_count,
                    "categories": [
                        {
                            "name": cat.name,
                            "is_nsfw": cat.nsfw,
                            "stage_channels": [
                                {
                                    "name": c.name,
                                    "id": c.id,
                                    "is_nsfw": c.nsfw,
                                    "user_limit": c.user_limit,
                                    "connected_listeners": {
                                        "count": len(c.listeners),
                                        "members": [m.display_name for m in c.listeners]
                                    },
                                    "channel_url": c.jump_url
                                } for c in cat.stage_channels
                            ],
                            "voice_channels": [
                                {
                                    "name": c.name,
                                    "id": c.id,
                                    "is_nsfw": c.nsfw,
                                    "user_limit": c.user_limit,
                                    "connected_members": {
                                        "count": len(c.members),
                                        "members": [m.display_name for m in c.members]
                                    },
                                    "channel_url": c.jump_url
                                } for c in cat.voice_channels
                            ],
                            "text_channels": [
                                {
                                    "name": c.name,
                                    "id": c.id,
                                    "is_nsfw": c.nsfw,
                                    "channel_url": c.jump_url
                                } for c in cat.text_channels
                            ],
                        } for cat in message.guild.categories
                    ]
                }
            })
            rt_data.update({
                "members_count": message.guild.member_count,
                "members": [{
                    "display_name": m.display_name,
                    "roles": [
                        {
                            "name": r.name,
                            "color": '#{:06X}'.format(r.color.value),
                            "created_at": r.created_at.strftime("%d/%m/%Y at %H:%M:%S")
                        } for r in m.roles
                    ],
                    "mention_string": m.mention,
                } for m in message.guild.members]
            })
        if message.thread is not None:
            rt_data.update({"thread": message.thread.name})

        return rt_data

    async def send_status_typing(self, message: discord.Message):
        await message.channel.typing()

    def can_read_history(self, channel) -> bool:
        # Check if the bot can read message history in the channel
        if hasattr(channel, 'permissions_for'):
            perms = channel.permissions_for(channel.guild.me) if channel.guild else None
            if perms and not perms.read_message_history:
                return False
        return True

    async def send_response(self, origin: discord.Message | discord.Interaction, text: str, ephemeral: bool = False, *args, **kwargs):
        if isinstance(origin, discord.Message):
            await origin.channel.send(text, *args, **kwargs)
        elif isinstance(origin, discord.Interaction):
            await origin.response.send_message(text, *args, ephemeral=ephemeral, **kwargs)
        else:
            raise TypeError(
                f"expected `origin` to be an instance of discord.Message or discord.Interaction, but got {type(origin)}")

    async def send_reply(self, message: discord.Message | discord.Interaction, text: str, delay: int = None, ephemeral: bool = False):
        if isinstance(message, discord.Message):
            # delay adds realism
            if delay is not None and delay > 0:
                async with message.channel.typing():
                    await asyncio.sleep(delay)

        num_retries = 5
        for i in range(num_retries):
            try:
                if isinstance(message, discord.Interaction):
                    await self.send_response(message, text, ephemeral=ephemeral)
                else:
                    if message.channel.type == discord.ChannelType.private:
                        await self.send_response(message, text)
                    else:
                        if self.can_read_history(message.channel):
                            await self.send_response(message, text, reference=message)
                        else:
                            await self.send_response(f"{message.author.mention} {text}")
                break
            except discord.Forbidden as e:
                logging.exception(f"Forbidden")
                raise RuntimeError(f"Cannot send message in channel {message.channel.id}")
            except discord.HTTPException as e:
                logging.warning(f"HTTPException while sending message: {e}, retrying ({i}/{num_retries})")
        else:
            raise RuntimeError(f"There was an unexpected error while send a message in channel {message.channel.id}")

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
        return message.author.id == bot_user.id

    async def fetch_attachment_images(self, message: discord.Message) -> list[ImageCache]:
        supported_image_types = {'image/jpeg', 'image/png', 'image/webp'}
        attached_images = []
        for attachment in message.attachments:
            if attachment.content_type in supported_image_types:
                image_bytes = await attachment.read()
                attached_images.append(ImageCache(
                    image_bytes=image_bytes,
                ))
        return attached_images

    def get_message_text(self, message: discord.Message) -> str:
        return message.content if message.content else ''

    async def fetch_message_reply(self, message: discord.Message) -> discord.Message:
        ref = message.reference
        if ref is None:
            return None
        if ref.cached_message:
            return ref.cached_message
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
        if hasattr(interaction.user, 'guild_permissions') and interaction.user.guild_permissions.administrator:
            return True
        return False

    async def add_reaction(self, message: discord.Message, emoji: str):
        try:
            await message.add_reaction(emoji)
        except discord.Forbidden:
            logging.exception("unable to add reaction to a message")
