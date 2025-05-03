import json
import math
import logging
import asyncio
import os

from dotenv import load_dotenv

import discord
from discord import app_commands

from api.conversation import ConversationStorage, LLMConversation
import api.chatting as Chat

from api.utils import ImageCache

logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s / %(name)s] %(message)s',
    level=logging.WARNING
)

class PixiClient(discord.Client):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents = intents, *args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

# constats

HASH_PREFIX = "Discord-1"
PERSONA = Chat.AssistantPersona.from_dict(json.load(open("persona.json", "rb")))

CLIENT = PixiClient()
STORAGE = ConversationStorage(persona = PERSONA, hash_prefix = HASH_PREFIX)

# messages

class Messages:
    SOMETHING_WENT_WRONG = "Something went wrong! ohh no... :sob:"
    I_RATHER_NOT_ANSWER = "I Rather not answer that honestly..."
    FORBIDDEN_ACTION_CHANNEL = "I cannot do that in this channel..." 

# helper functions

def strip_message(message: str):
    remove_starts = ["!pixi", "!pix", "!p", "@pixiaibot", "@pixiai", "@pixi", "@pixibot"]
    for rs in remove_starts:
        if message.lower().startswith(rs):
            message = message[len(rs):]
    return message

async def trace_message(message: discord.Message) -> tuple[str, discord.Message]:
    msg_text = strip_message(message.content)
    # Remove bot mention if present
    if CLIENT.user:
        mention_str = CLIENT.user.mention
        if mention_str in msg_text:
            msg_text = msg_text.replace(mention_str, "").strip()
    # If message is empty and is a reply, trace the reply
    reply_message = None
    if msg_text == "" and message.reference is not None and message.reference.message_id is not None:
        reply_message = await message.channel.fetch_message(message.reference.message_id)
        return await trace_message(reply_message)
    if reply_message is not None and reply_message.author.id == CLIENT.user.id:
        reply_message = message
    return msg_text, message

async def get_unique_chat_identifier(message: discord.Message | discord.Integration) -> str:
    channel = message.channel
    
    # Check if the message is in a guild (server)
    if channel.guild is not None:
        # Use the guild ID as the unique identifier
        return f"guild#{channel.guild.id}"
    
    # If the message is in a DM or group chat, use the channel ID
    return f"channel#{channel.id}"

async def get_convo_from_message(message: discord.Message) -> LLMConversation:
    return STORAGE.get(await get_unique_chat_identifier(message))

async def pixi_resp_retry(role_message: Chat.RoleMessage, message: discord.Message):
    # catch the error 3 times and retry, if the error continues
    # retry once more without catching the error to see the error
    for i in range(3):
        try:
            return await pixi_resp(role_message, message)
        except Exception as e:
            logging.warning(f"Retrying after error: {e}")
            continue
    return await pixi_resp(role_message, message)

# Helper to check if command is in DM or user is admin
def is_dm_or_admin(interaction: discord.Interaction) -> bool:
    if isinstance(interaction.channel, discord.DMChannel):
        return True
    if hasattr(interaction.user, 'guild_permissions') and interaction.user.guild_permissions.administrator:
        return True
    return False

def can_read_history(channel) -> bool:
    # Check if the bot can read message history in the channel
    if hasattr(channel, 'permissions_for'):
        perms = channel.permissions_for(channel.guild.me) if channel.guild else None
        if perms and not perms.read_message_history:
            return False
    return True

async def send_reply(message: discord.Message, text: str, delay: int = None) -> bool:
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
        except discord.HTTPException as e:
            logging.warning(f"HTTPException while sending message: {e}, retrying ({i}/{num_retries})")
        else:
            return True
    return False
        
def get_real_time_data(message: discord.Message):
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
        rt_data.update({"guild": message.guild.name})
    if message.thread is not None:
        rt_data.update({"thread": message.thread.name})
    
    return rt_data
        
# actually respond the message
# this function is called by the retry function

async def pixi_resp(role_message: Chat.RoleMessage, message: discord.Message):
    convo = await get_convo_from_message(message)
    messages_checkpoint = convo.get_messages().copy()
    async with message.channel.typing():
        convo.update_realtime(get_real_time_data(message))
        responded = False
        try:
            for resp in convo.live_chat(role_message, allow_ignore = False):
                # the model may return "NO_RESPONSE" if it doesn't want to respond
                if resp.strip() != "" or resp == "NO_RESPONSE":
                    delay = (0.5 + (1.8 ** math.log2(1+len(resp))) / 20)
                    await send_reply(message, resp, delay)
        except discord.Forbidden:
            logging.exception(f"Cannot send message in {message.channel.name} ({message.channel.id})")
        except discord.NotFound:
            logging.exception(f"Message not found: {message.id}")
        except Exception as e:
            logging.exception("Unknown error")
        else:
            responded = True

        if responded:
            convo.save()
            logging.info("responded to a message!")
        else:
            logging.warning("there was no response to the message.")
            convo.set_messages(messages_checkpoint)
            await send_reply(message, Messages.SOMETHING_WENT_WRONG)

# events

@CLIENT.event
async def on_message(message: discord.Message):
    if message.author == CLIENT.user or message.author.bot:
        return
    convo_id = await get_unique_chat_identifier(message)
    convo = STORAGE.get(convo_id)
    
    # --- IMAGE HANDLING START ---
    supported_image_types = ['image/jpeg', 'image/png', 'image/webp']
    attached_images = []
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type in supported_image_types:
                image_bytes = await attachment.read()
                attached_images.append(ImageCache(
                    image_bytes = image_bytes,
                ))
    # --- IMAGE HANDLING END ---
    if message is None or message.content == "":
        if len(attached_images) == 0:
            return
    message_text = message.content if message.content else ''
    reply_message, reply_message_text = None, None
    if message.reference is not None and message.reference.message_id is not None:
        reply_message = await message.channel.fetch_message(message.reference.message_id)
        reply_message_text = None if reply_message is None else reply_message.content
    metadata = {"from": message.author.display_name}
    clean_message = ""
    # Check if the message is a command, a reply to the bot, a DM, or mentions the bot
    bot_mentioned = CLIENT.user in message.mentions if CLIENT.user else False
    if message_text.lower().startswith("!p") or message_text.lower().startswith("!pixi"):
        clean_message, _ = await trace_message(message)
    elif reply_message and reply_message.author.id == CLIENT.user.id:
        clean_message, _ = await trace_message(message)
    elif message.channel.type == discord.ChannelType.private:
        clean_message, _ = await trace_message(message)
    elif bot_mentioned:
        clean_message, _ = await trace_message(message)
    if clean_message == "" and len(attached_images) == 0:
        return
    # check if the message is a reply to a bot message
    if reply_message is not None:
        metadata.update({"reply to message": {}})
        replmessage_text = reply_message_text or ""
        if replmessage_text.lower().startswith("!pixi"):
            replmessage_text = replmessage_text[6:]
        elif replmessage_text.lower().startswith("!p"):
            replmessage_text = replmessage_text[3:]
        reply_optimization = -1
        
        convo_messages = convo.get_messages()
        matching_messages = [msg.content for msg in convo_messages if replmessage_text in msg.content]
        if matching_messages:
            if convo_messages[-1].content in matching_messages:
                reply_optimization = 2
            else:
                reply_optimization = 1
        if reply_optimization == 2:
            # completely ignore reply context
            pass
        elif reply_message and reply_message.author.id == CLIENT.user.id:
            if reply_optimization == 1:
                metadata["reply to message"].update({
                    "from": "[YOU]",
                    "partial content": replmessage_text[:64]
                })
            else:
                metadata["reply to message"].update({
                    "from": "[YOU]",
                    "content": replmessage_text
                })
        else:
            if reply_optimization == 1:
                metadata["reply to message"].update({
                    "from": reply_message.author.display_name,
                    "partial content": replmessage_text[:64]
                })
            else:
                metadata["reply to message"].update({
                    "from": reply_message.author.display_name,
                    "content": replmessage_text
                })
    # --- IMAGE-AWARE ROLE MESSAGE ---
    role_message = Chat.RoleMessage(role=Chat.Role.USER, content=clean_message, metadata=metadata, images=attached_images)
    await pixi_resp_retry(role_message, message)

# Slash command: /reset
@CLIENT.tree.command(name="reset", description="Reset the conversation with Pixi.")
async def reset_command(interaction: discord.Interaction):
    if not is_dm_or_admin(interaction):
        await interaction.response.send_message("You must be a guild admin or use this in DMs.", ephemeral=True)
        return
    identifier = await get_unique_chat_identifier(interaction)
    logging.info(f"the conversation in {identifier} has been reset.")
    STORAGE.remove(identifier)
    await interaction.response.send_message("Wha- Where am I?!")

# Slash command: /notes
@CLIENT.tree.command(name="notes", description="Toggle notes visibility for Pixi.")
async def notes_command(interaction: discord.Interaction):
    if not is_dm_or_admin(interaction):
        await interaction.response.send_message("You must be a guild admin or use this in DMs.", ephemeral=True)
        return
    identifier = await get_unique_chat_identifier(interaction)
    is_notes_visible = (await get_convo_from_message(identifier)).toggle_notes()
    notes_message = "Notes are now visible." if is_notes_visible else "Notes are no longer visible"
    await interaction.response.send_message(notes_message)

if __name__ == '__main__':
    print("starting...")
    load_dotenv()  # take environment variables
    CLIENT.run(os.environ["DISCORD_BOT_TOKEN"])