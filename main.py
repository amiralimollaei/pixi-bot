import math
import logging
import time
import os

from api.conversation import ConversationStorage, LLMConversation
import api.chatting as Chat

from api.utils import Ansi, load_dotenv
from enums import Platform
from enums.messages import Messages

from api.reflection import ReflectionAPI

logging.basicConfig(
    format=f"{Ansi.GREY}[{Ansi.BLUE}%(asctime)s{Ansi.GREY}] {Ansi.GREY}[{Ansi.YELLOW}%(levelname)s / %(name)s{Ansi.GREY}] {Ansi.WHITE}%(message)s",
    level=logging.INFO
)

## https://github.com/langchain-ai/langchain/issues/14065#issuecomment-1834571761
# Get the logger for 'httpx'
httpx_logger = logging.getLogger("httpx")
# Set the logging level to WARNING to ignore INFO and DEBUG logs
httpx_logger.setLevel(logging.WARNING)

# constants

COMMAND_PREFIXES = ["!pixi", "!pix", "!p", "@pixiaibot", "@pixi"]

# helper functions

def remove_prefixes(text: str):
    for prefix in COMMAND_PREFIXES:
        text = text.removeprefix(prefix)
    return text

class PixiClient:
    def __init__(self, platform: Platform, persona_file: str = "persona.json"):
        self.platform = platform
        self.persona = Chat.AssistantPersona.from_json(persona_file)
        self.storage = ConversationStorage(persona = self.persona, hash_prefix = platform)
        self.reflection_api = ReflectionAPI(platform = platform)
        
        match platform:
            case Platform.DISCORD:
                self.init_discord()
            case Platform.TELEGRAM:
                self.init_telegram()
    
    def init_discord(self):
        import discord
        from discord import app_commands
        
        self.token = os.environ["DISCORD_BOT_TOKEN"]
        
        class DiscordClient(discord.Client):
            def __init__(self, *args, **kwargs):
                intents = discord.Intents.default()
                intents.message_content = True
                intents.members = True
                super().__init__(intents = intents, *args, **kwargs)
                self.tree = app_commands.CommandTree(self)

            async def setup_hook(self):
                await self.tree.sync()
        
        client = DiscordClient()
        self.client = client
        
        @client.event
        async def on_message(*args, **kwargs):
            return await self.on_message(*args, **kwargs)
        
        # Slash command: /reset
        @client.tree.command(name="reset", description="Reset the conversation with Pixi.")
        async def reset_command(interaction: discord.Interaction):
            if not self.reflection_api.is_dm_or_admin(interaction):
                await interaction.response.send_message("You must be a guild admin or use this in DMs.", ephemeral=True)
                return
            identifier = self.reflection_api.get_identifier_from_message(interaction)
            logging.info(f"the conversation in {identifier} has been reset.")
            self.storage.remove(identifier)
            await interaction.response.send_message("Wha- Where am I?!")

        # Slash command: /notes
        @client.tree.command(name="notes", description="Toggle notes visibility for Pixi.")
        async def notes_command(interaction: discord.Interaction):
            if not self.reflection_api.is_dm_or_admin(interaction):
                await interaction.response.send_message("You must be a guild admin or use this in DMs.", ephemeral=True)
                return
            identifier = self.reflection_api.get_identifier_from_message(interaction)
            is_notes_visible = self.get_conversation(identifier).toggle_notes()
            notes_message = "Notes are now visible." if is_notes_visible else "Notes are no longer visible"
            await interaction.response.send_message(notes_message)
                            
    def init_telegram(self):
        import telegram
        from telegram.constants import ChatAction
        from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters
        
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        
        async def on_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            return await self.on_message(message)
        
        async def reset(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            convo_id = self.reflection_api.get_identifier_from_message(message)
            try:
                self.storage.remove(convo_id)
                logging.info(f"The conversation in {convo_id} has been reset.")
                await context.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
                await context.bot.send_message(chat_id=update.effective_chat.id, reply_to_message_id=message.message_id, text="Wha- Where am I?!")
            except Exception as e:
                logging.exception(f"Failed to reset conversation for {convo_id}")
                await context.bot.send_message(chat_id=update.effective_chat.id, text="Failed to reset conversation.")

        async def start(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Hiiiii, how's it going?")

        async def notes(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            try:
                convo_id = self.reflection_api.get_identifier_from_message(message)
                convo = self.get_conversation(convo_id)
                is_notes_visible = convo.toggle_notes()
                await self.reflection_api.send_reply(message, f"notes set to {is_notes_visible}")
            except Exception as e:
                logging.exception(f"Failed to toggle notes")
                await self.reflection_api.send_reply(message, "Failed to toggle notes.")       
                
        application = Application.builder().token(self.token).build()
        self.application = application

        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('reset', reset))
        application.add_handler(CommandHandler('notes', notes))
        application.add_handler(MessageHandler(filters.TEXT, callback=on_message))
        application.add_handler(MessageHandler(filters.PHOTO, callback=on_message))
    
    def get_conversation(self, identifier: str) -> LLMConversation:
        return self.storage.get(identifier)
    
    async def pixi_resp(self, role_message: Chat.RoleMessage, message, allow_ignore: bool = True):
        start_typing_time = time.time()
        conversation = self.get_conversation(self.reflection_api.get_identifier_from_message(message))
        conversation.update_realtime(self.reflection_api.get_realtime_data(message))
        messages_checkpoint = conversation.get_messages().copy()
        
        responded = False
        try:
            await self.reflection_api.send_status_typing(message)

            for resp in conversation.live_chat(role_message, allow_ignore = allow_ignore):
                # the model may return "NO_RESPONSE" if it doesn't want to respond
                if resp.strip() != "" and resp != "NO_RESPONSE":
                    response_time = time.time() - start_typing_time
                    delay = max(0, (0.5 + (1.8 ** math.log2(1+len(resp))) / 10) - response_time)
                    await self.reflection_api.send_reply(message, resp, delay)
                    start_typing_time = time.time()
                    responded = True
        except ReflectionAPI.Forbidden:
            logging.exception(f"Cannot send message in channel {message.channel.id}")
        except Exception:
            logging.exception(f"Unknown error while responding to a message in channel {message.channel.id}")
            await self.reflection_api.send_reply(message, Messages.SOMETHING_WENT_WRONG)

        if responded:
            conversation.save()
            logging.debug("responded to a message and saved the conversation.")
        else:
            conversation.set_messages(messages_checkpoint)
            if not allow_ignore:
                raise RuntimeError("there was no response to a message while ignoring a message is not allowed.")
            else:
                logging.warning("there was no response to the message while ignoring a message is allowed.")
    
    async def pixi_resp_retry(self, role_message: Chat.RoleMessage, message, num_retry: int = 3):
        # catch the error 3 times and retry, if the error continues
        # retry once more without catching the error to see the error
        for i in range(num_retry):
            try:
                return await self.pixi_resp(role_message, message)
            except Exception as e:
                logging.exception("There was an error in `pixi_resp`")
                logging.warning(f"Retrying ({i}/{num_retry})")
                continue
        return await self.pixi_resp(role_message, message)

    async def on_message(self, message):
        
        # we should not process our own messages again
        if self.reflection_api.is_message_from_the_bot(message):
            return

        message_text = self.reflection_api.get_message_text(message)
        
        # Check if the message is a command, a reply to the bot, a DM, or mentions the bot
        bot_mentioned = self.reflection_api.is_bot_mentioned(message)
        is_inside_dm = self.reflection_api.is_inside_dm(message)
        if is_inside_dm or bot_mentioned or message_text.lower().startswith(tuple(COMMAND_PREFIXES)):
            message_text = remove_prefixes(message_text)
        else:
            return

        convo_id = self.reflection_api.get_identifier_from_message(message)
        convo = self.storage.get(convo_id)

        attached_images = await self.reflection_api.fetch_attachment_images(message)

        metadata = dict(from_user = self.reflection_api.get_sender_name(message))

        # check if the message is a reply to a bot message
        reply_message = await self.reflection_api.fetch_message_reply(message)
        if reply_message is not None:
            reply_message_text = self.reflection_api.get_message_text(reply_message)
            reply_message_text = remove_prefixes(reply_message_text)
            metadata.update({"reply to message": {}})
            
            reply_optimization = -1
            
            convo_messages = convo.get_messages()
            
            # if the reply is to the last message that is sent by the bot, we don't need to do anything.
            matching_messages = [msg.content for msg in convo_messages if reply_message_text in msg.content]
            if matching_messages:
                if convo_messages[-1].content in matching_messages:
                    reply_optimization = 2
                else:
                    reply_optimization = 1
            if reply_optimization == 2:
                # completely ignore reply context
                pass
            elif reply_message and self.reflection_api.is_message_from_the_bot(reply_message):
                if reply_optimization == 1:
                    metadata["reply to message"].update({
                        "from": "[YOU]",
                        "partial content": reply_message_text[:64]
                    })
                else:
                    metadata["reply to message"].update({
                        "from": "[YOU]",
                        "content": reply_message_text
                    })
            else:
                if reply_optimization == 1:
                    metadata["reply to message"].update({
                        "from": reply_message.author.display_name,
                        "partial content": reply_message_text[:64]
                    })
                else:
                    metadata["reply to message"].update({
                        "from": reply_message.author.display_name,
                        "content": reply_message_text
                    })
        # convert everything into `RoleMessage``
        role_message = Chat.RoleMessage(role=Chat.Role.USER, content=message_text, metadata=metadata, images=attached_images)
        await self.pixi_resp_retry(role_message, message)
    
    def run(self):
        match self.platform:
            case Platform.DISCORD:
                self.client.run(self.token, log_handler=None)
            case Platform.TELEGRAM:
                self.application.run_polling()
            

if __name__ == '__main__':
    import argparse
    
    # load environment variables
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the Pixi bot.")
    parser.add_argument(
        "--platform",
        type=str,
        choices=[p.name.lower() for p in Platform],
        required=True,
        help="Platform to run the bot on (telegram or discord)."
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Set the logging level."
    )
    args = parser.parse_args()

    # Set logging level
    logging.getLogger().setLevel(args.log_level.upper())

    # Set platform
    platform = Platform[args.platform.upper()]

    # run
    pixi_client = PixiClient(platform=platform)
    pixi_client.run()