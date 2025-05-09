import logging
import asyncio

from enums import Platform

import discord

from ..utils import ImageCache

# helper functions:

def strip_message(message: str):
    remove_starts = ["!pixi", "!pix", "!p", "@pixiaibot", "@pixiai", "@pixi", "@pixibot"]
    for rs in remove_starts:
        if message.lower().startswith(rs):
            message = message[len(rs):]
    return message

class ReflectionAPI:
    def __init__(self):
        self.platform = Platform.DISCORD
        logging.debug("ReflectionAPI has been initilized for DISCORD.")

    def get_identifier_from_message(self, message: discord.Message | discord.Integration) -> str:
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
                rt_data.update({"channel": "DM / Private Chat"})
            case discord.ChannelType.group:
                rt_data.update({"channel": "Group Chat"})
            case discord.ChannelType.text:
                channle_name = message.channel.name
                rt_data.update({"channel": {"Text Channel": {"name": channle_name}}})
            case _:
                channle_name = getattr(message.channel, 'name', "Unknown")
                rt_data.update({"channel": {"Channel": {"name": channle_name}}})

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
                            "color": r.color,
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
    
    async def send_reply(self, message: discord.Message, text: str, delay: int = None) -> bool:
        def can_read_history(channel) -> bool:
            # Check if the bot can read message history in the channel
            if hasattr(channel, 'permissions_for'):
                perms = channel.permissions_for(channel.guild.me) if channel.guild else None
                if perms and not perms.read_message_history:
                    return False
            return True
        
        # delay adds realism
        if delay is not None and delay > 0:
            async with message.channel.typing():
                await asyncio.sleep(delay)
        
        num_retries = 5
        for i in range(num_retries):
            try:
                if message.channel.type == discord.ChannelType.private:
                    await message.channel.send(text)
                else:
                    if can_read_history(message.channel):
                        await message.channel.send(text, reference=message)
                    else:
                        await message.channel.send(f"{message.author.mention} {text}")
            except discord.Forbidden as e:
                logging.exception(f"Cannot send message in channel {message.channel.id}")
                raise RuntimeError(f"Cannot send message in channel {message.channel.id}")
            except discord.HTTPException as e:
                logging.warning(f"HTTPException while sending message: {e}, retrying ({i}/{num_retries})")
            else:
                return
        raise RuntimeError(f"There was an unexpected error while send a message in channel {message.channel.id}")
    
    async def trace_message(self, message: discord.Message) -> tuple[str, discord.Message]:
        msg_text = strip_message(message.content)

        bot_user = message._state.user
        # Remove bot mention if present
        if bot_user:
            mention_str = bot_user.mention
            if mention_str in msg_text:
                msg_text = msg_text.replace(mention_str, "").strip()
        # If message is empty and is a reply, trace the reply
        reply_message = None
        if msg_text == "" and message.reference is not None and message.reference.message_id is not None:
            reply_message = await message.channel.fetch_message(message.reference.message_id)
            return await self.trace_message(reply_message)
        if reply_message is not None and reply_message.author.id == bot_user.id:
            reply_message = message
        return msg_text, message
    
    
    def get_sender_id(self, message: discord.Message):
        return message.author.id
    
    def get_sender_name(self, message: discord.Message):
        return message.author.display_name
        
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
                    image_bytes = image_bytes,
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

if __name__ == "__main__":
    ReflectionAPI()