from dataclasses import asdict
import asyncio
import json
import logging
import math
import os
import time


from pixi.agents import RetrievalAgent
from pixi.apis import AsyncGiphyAPI, AsyncWikimediaAPI
from pixi.chatbot import AssistantPersona, AsyncChatbotInstance, CachedAsyncChatbotFactory
from pixi.chatting import ChatMessage
from pixi.database import DirectoryDatabase
from pixi.enums import ChatRole, Messages, Platform
from pixi.reflection import ReflectionAPI

# constants

COMMAND_PREFIXES = ["!pixi", "!pix", "!p"]


# helper functions

def remove_prefixes(text: str):
    for prefix in COMMAND_PREFIXES:
        text = text.removeprefix(prefix)
    return text


class PixiClient:
    def __init__(self,
                 platform: Platform,
                 *,
                 model: str,
                 helper_model: str,
                 api_url: str,
                 persona_file: str = "persona.json",
                 database_names: list[str] | None = None,
                 enable_tool_calls: bool = False,
                 log_tool_calls: bool = False
                 ):
        self.platform = platform
        self.persona = AssistantPersona.from_json(persona_file)
        self.chatbot_factory = CachedAsyncChatbotFactory(
            model=model,
            base_url=api_url,
            persona=self.persona,
            hash_prefix=platform,
            log_tool_calls=log_tool_calls,
        )
        self.reflection_api = ReflectionAPI(platform=platform)
        self.helper_model = helper_model
        self.enable_tool_calls = enable_tool_calls

        self.database_names = database_names or []
        self.database_tools_initalized = asyncio.Event()

        try:
            self.giphy_api = AsyncGiphyAPI()
        except KeyError:
            logging.warning("GIPHY_API_KEY is not set, GIF features will not be available.")
            self.giphy_api = None

        # TODO: add configurable wikis
        self.init_mediawiki_tools(url="https://minecraft.wiki/", wiki_name="minecraft")
        self.init_mediawiki_tools(url="https://www.wikipedia.org/w/", wiki_name="wikipedia")

        if not enable_tool_calls:
            logging.warning("Tool calls are disabled, running with limited functionality.")

        match platform:
            case Platform.DISCORD:
                self.init_discord()

            case Platform.TELEGRAM:
                self.init_telegram()

    async def __init_database_tools(self):
        await asyncio.gather(*(
            self.init_database_tool(database_name) for database_name in self.database_names
        ))
        self.database_tools_initalized.set()

    async def init_database_tool(self, database_name: str):
        database_api = await DirectoryDatabase.from_directory(database_name)

        async def get_entry_as_str(entry_id: int):
            return json.dumps(asdict(await database_api.get_entry(entry_id)), ensure_ascii=False, indent=4)
        
        async def search_database(keyword: str):
            return [asdict(match) for match in await database_api.search(keyword)]

        self.chatbot_factory.register_tool(
            name=f"search_{database_name}_database",
            func=search_database,
            parameters=dict(
                type="object",
                properties=dict(
                    keyword=dict(
                        type="string",
                        description=f"The search keyword to find matches in the database text from the {database_name} database",
                    ),
                ),
                required=["keyword"],
                additionalProperties=False
            ),
            description=f"Searches the {database_name} database based on a keyword and returns the entry metadata. you may use this function multiple times to find the specific information you're looking for."
        )

        async def query_database(query: str, ids: str = None):
            return await RetrievalAgent(
                model=self.helper_model,
                context=await asyncio.gather(*(get_entry_as_str(int(entry_id.strip())) for entry_id in ids.split(",")))
            ).retrieve(query)

        self.chatbot_factory.register_tool(
            name=f"query_{database_name}_database",
            func=query_database,
            parameters=dict(
                type="object",
                properties=dict(
                    query=dict(
                        type="string",
                        description=f"A question or a statement that you want to find information about.",
                    ),
                    ids=dict(
                        type="string",
                        description=f"Comma-seperated numerical entry ids to fetch and query information from, use `search_{database_name}_database` to optain entry ids based a search term.",
                    ),
                ),
                required=["query", "ids"],
                additionalProperties=False
            ),
            description=f"runs an LLM agent to fetch and query the contents of the {database_name} database using the entry ids for finding relevent entries and a more detailed query for finding relevent information, note that this will not return all the information that the page contains, you might need to use this command multiple times to get all the information out of the database entry."
        )

    def init_mediawiki_tools(self, url: str, wiki_name: str):
        wiki_api = AsyncWikimediaAPI(url)

        async def search_wiki(keyword: str):
            return [asdict(search_result) for search_result in await wiki_api.search(keyword)]

        self.chatbot_factory.register_tool(
            name=f"search_wiki_{wiki_name}",
            func=search_wiki,
            parameters=dict(
                type="object",
                properties=dict(
                    keyword=dict(
                        type="string",
                        description=f"The search keyword to find matches in the wiki text from the {wiki_name} wiki",
                    ),
                ),
                required=["keyword"],
                additionalProperties=False
            ),
            description=f"Searches the {wiki_name} wiki based on a keyword. returns the page URL and Title, and optionally the description of the page. you may use this function multiple times to find the specific page you're looking for."
        )

        self.chatbot_factory.register_tool(
            name=f"search_wiki_{wiki_name}",
            func=search_wiki,
            parameters=dict(
                type="object",
                properties=dict(
                    keyword=dict(
                        type="string",
                        description=f"The search keyword to find matches in the wiki text from the {wiki_name} wiki",
                    ),
                ),
                required=["keyword"],
                additionalProperties=False
            ),
            description=f"Searches the {wiki_name} wiki based on a keyword. returns the page URL and Title, and optionally the description of the page. you may use this function multiple times to find the specific page you're looking for."
        )

        async def query_wiki_content(titles: str, query: str):
            return await RetrievalAgent(
                model=self.helper_model,
                context=await asyncio.gather(*(wiki_api.get_raw(t.strip()) for t in titles.split("|")))
            ).retrieve(query)

        self.chatbot_factory.register_tool(
            name=f"query_wiki_content_{wiki_name}",
            func=query_wiki_content,
            parameters=dict(
                type="object",
                properties=dict(
                    query=dict(
                        type="string",
                        description=f"A question or a statement that you want to find information about.",
                    ),
                    titles=dict(
                        type="string",
                        description=f"Page titles to fetch and query information from, seperated by a delimiter character: `|`. use `search_wiki_{wiki_name}` to optain page titles based a search term.",
                    ),
                ),
                required=["query", "titles"],
                additionalProperties=False
            ),
            description=f"runs an LLM agent to fetch and retrieve relevent information from the contents of the {wiki_name} wiki. \
                This will not return all the information that the page contains, you might need to use this command multiple \
                times to find the information you're looking for."
        )

    def init_discord_tools(self):
        async def fetch_channel_history(channel_id: str, n: str):
            logging.info(f"calling fetch_channel_history({channel_id=}, {n=})")

            channel_id = int(channel_id)
            channel = await self.client.fetch_channel(channel_id)
            n = int(n)

            messages = []
            async for message in channel.history(limit=n):
                messages.append(dict(
                    from_user=self.reflection_api.get_sender_information(message),
                    message_text=self.reflection_api.get_message_text(message)
                ))

            return messages[::-1]

        async def search_gif(query: str):
            logging.info(f"calling search_gif({query=})")
            resp = await self.giphy_api.search(query, rating="pg")
            data = resp.get("data")
            results = []
            if data is None:
                logging.warning(f"No GIFs found for query: {query}")
                return []
            for gif in data:
                if id := gif.get("id"):
                    results.append(dict(
                        slug=gif.get("slug"),
                        title=gif.get("title"),
                        rating=gif.get("rating"),
                        url=f"https://i.giphy.com/{id}.webp"
                    ))
            return results

        self.chatbot_factory.register_tool(
            name="fetch_channel_history",
            func=fetch_channel_history,
            parameters=dict(
                type="object",
                properties=dict(
                    channel_id=dict(
                        type="string",
                        description="The numerical channel id, which is used to identify the channel.",
                    ),
                    n=dict(
                        type="integer",
                        description="the number of messages to fetch from the channel",
                    ),
                ),
                required=["channel_id"],
                additionalProperties=False
            ),
            description="Fetches the last `n` message from a text channel"
        )

        if self.giphy_api is not None:
            self.chatbot_factory.register_tool(
                name="search_gif",
                func=search_gif,
                parameters=dict(
                    type="object",
                    properties={
                        "query": {
                            "type": "string",
                            "description": "The search query.",
                        },
                    },
                    required=["query"],
                    additionalProperties=False
                ),
                description="searches the internet for the most relevent GIFs based on a query, to send a gif send the GIF's url as a distinct chat message."
            )

    async def notes_command(self, interaction):
        if not await self.reflection_api.is_dm_or_admin(interaction):
            await self.reflection_api.send_reply(interaction, "You must be a guild admin or use this in DMs.", ephemeral=True)
            return
        try:
            identifier = self.reflection_api.get_identifier_from_message(interaction)
            conversation = self.get_conversation(identifier)
            is_notes_visible = conversation.toggle_notes()
            notes_message = "Notes are now visible." if is_notes_visible else "Notes are no longer visible"
            await self.reflection_api.send_reply(interaction, notes_message)
        except Exception:
            logging.exception(f"Failed to toggle notes")
            await self.reflection_api.send_reply(interaction, "Failed to toggle notes.")

    async def reset_command(self, interaction):
        if not await self.reflection_api.is_dm_or_admin(interaction):
            await self.reflection_api.send_reply(interaction, "You must be a guild admin or use this in DMs.", ephemeral=True)
            return
        identifier = self.reflection_api.get_identifier_from_message(interaction)
        logging.info(f"the conversation in {identifier} has been reset.")
        self.chatbot_factory.remove(identifier)
        await self.reflection_api.send_reply(interaction, "Wha- Where am I?!")

    def init_discord(self):
        import discord
        from discord import app_commands

        if self.enable_tool_calls:
            self.init_discord_tools()

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

        client = DiscordClient()
        self.client = client

        @client.event
        async def on_message(*args, **kwargs):
            return await self.on_message(*args, **kwargs)

        # Slash command: /reset
        @client.tree.command(name="reset", description="Reset the conversation.")
        async def reset_command(interaction: discord.Interaction):
            await self.reset_command(interaction)

        # Slash command: /notes
        @client.tree.command(name="notes", description="Toggle notes visibility.")
        async def notes_command(interaction: discord.Interaction):
            await self.notes_command(interaction)

    def init_telegram(self):
        import telegram
        from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters

        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if self.token is None:
            logging.warning("TELEGRAM_BOT_TOKEN environment variable is not set, unable to initialize telegram bot.")
            return

        async def on_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            return await self.on_message(message)

        async def reset(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            await self.reset_command(message)

        async def start(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            await self.reflection_api.send_reply(message, "Hiiiii, how's it going?")

        async def notes(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
            message = update.message
            await self.notes_command(message)

        application = Application.builder().token(self.token).build()
        self.application = application

        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('reset', reset))
        application.add_handler(CommandHandler('notes', notes))
        application.add_handler(MessageHandler(filters.TEXT, callback=on_message))
        application.add_handler(MessageHandler(filters.PHOTO, callback=on_message))

    def get_conversation(self, identifier: str) -> AsyncChatbotInstance:
        return self.chatbot_factory.get(identifier)

    async def pixi_resp(self, chat_message: ChatMessage, message, allow_ignore: bool = True):
        if not self.database_tools_initalized.is_set():
            await self.__init_database_tools()
            await self.database_tools_initalized.wait()

        start_typing_time = time.time()
        responded = False
        identifier = self.reflection_api.get_identifier_from_message(message)
        conversation = self.get_conversation(identifier)
        conversation.update_realtime(self.reflection_api.get_realtime_data(message))

        async def send_command(text):
            nonlocal responded
            nonlocal start_typing_time
            response_time = time.time() - start_typing_time

            delay = max(0, (0.5 + (1.8 ** math.log2(1+len(text))) / 10) - response_time)
            await self.reflection_api.send_reply(message, text, delay)

            start_typing_time = time.time()

            responded = True

        async def note_command(thoughts):
            if conversation.is_notes_visible:
                await self.reflection_api.send_reply(message, f"> {thoughts}")

        async def react_command(reaction):
            try:
                await self.reflection_api.add_reaction(message, reaction)
            except Exception:
                logging.exception(f"Failed to add reaction {reaction} to message {message.id}")

        conversation.add_command(
            name="send",
            field_name="message",
            function=send_command,
            descriptioon="sends a text as a distinct chat message, you MUST use this command to send a response, otherwise the user WILL NOT SEE it and your response will be IGNORED."
        )

        conversation.add_command(
            name="note",
            field_name="thoughts",
            function=note_command,
            descriptioon="annotates your thoughts, the user will not see these, it is completey private and only available to you, you Must do this before each message, thoughts should be at least 50 words"
        )

        conversation.add_command(
            name="react",
            field_name="emoji",
            function=react_command,
            descriptioon="react with an emoji (presented in utf-8) to the current message that you are responding to, you may react to messages that are shocking or otherwise in need of immediate emotional reaction, you can send multiple reactions by using this command multuple times."
        )

        messages_checkpoint = conversation.get_messages().copy()

        try:
            await self.reflection_api.send_status_typing(message)
            noncall_result = await conversation.stream_call(chat_message, allow_ignore=allow_ignore)
            if noncall_result:
                logging.warning(f"{noncall_result=}")
                # send non-call results as a message
                await send_command(noncall_result)
        except ReflectionAPI.Forbidden:
            logging.exception(f"Cannot send message in {identifier}")
        except Exception:
            logging.exception(f"Unknown error while responding to a message in {identifier}")
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

    async def pixi_resp_retry(self, chat_message: ChatMessage, message, num_retry: int = 3):
        # catch the error 3 times and retry, if the error continues
        # retry once more without catching the error to see the error
        for i in range(num_retry):
            try:
                return await self.pixi_resp(chat_message, message)
            except Exception as e:
                logging.exception("There was an error in `pixi_resp`")
                logging.warning(f"Retrying ({i}/{num_retry})")
                continue
        return await self.pixi_resp(chat_message, message)

    async def on_message(self, message):

        # we should not process our own messages again
        if self.reflection_api.is_message_from_the_bot(message):
            return

        message_text = self.reflection_api.get_message_text(message)

        # Check if the message is a command, a reply to the bot, a DM, or mentions the bot
        bot_mentioned = self.reflection_api.is_bot_mentioned(message)
        is_inside_dm = self.reflection_api.is_inside_dm(message)

        if not (is_inside_dm or bot_mentioned or message_text.lower().startswith(tuple(COMMAND_PREFIXES))):
            return

        message_text = remove_prefixes(message_text)

        convo_id = self.reflection_api.get_identifier_from_message(message)
        convo = self.chatbot_factory.get(convo_id)

        attached_images = await self.reflection_api.fetch_attachment_images(message)
        attached_audio = await self.reflection_api.fetch_attachment_audio(message)

        metadata = dict(
            from_user=self.reflection_api.get_sender_information(message)
        )

        # check if the message is a reply to a bot message
        reply_message = await self.reflection_api.fetch_message_reply(message)
        if reply_message is not None:
            reply_message_text = self.reflection_api.get_message_text(reply_message)
            reply_message_text = remove_prefixes(reply_message_text)
            metadata.update({"in_reply_to": {}})
            # if the reply is to the last message that is sent by the bot, we don't need to do anything.
            reply_optimization = -1
            convo_messages = convo.get_messages()
            matching_messages = [
                msg.content for msg in convo_messages if msg.content is not None and reply_message_text in msg.content]
            if matching_messages:
                if convo_messages[-1].content in matching_messages:
                    reply_optimization = 2
                else:
                    reply_optimization = 1
            if reply_optimization == 2:
                # completely ignore reply context
                logging.debug(f"completely ignore reply context for {convo_id=}")
            elif reply_message and self.reflection_api.is_message_from_the_bot(reply_message):
                if reply_optimization == 1:
                    metadata["in_reply_to"].update({
                        "from": "[YOU]",
                        "partial_content": reply_message_text[:64]
                    })
                else:
                    metadata["in_reply_to"].update({
                        "from": "[YOU]",
                        "message": reply_message_text
                    })
            else:
                if reply_optimization == 1:
                    metadata["in_reply_to"].update({
                        "from": self.reflection_api.get_sender_information(reply_message),
                        "partial_message": reply_message_text[:64]
                    })
                else:
                    metadata["in_reply_to"].update({
                        "from": self.reflection_api.get_sender_information(reply_message),
                        "message": reply_message_text
                    })
        # convert everything into `RoleMessage``
        role_message = ChatMessage(role=ChatRole.USER, content=message_text,
                                   metadata=metadata, images=attached_images, audio=attached_audio)
        await self.pixi_resp_retry(role_message, message)

    def run(self):
        match self.platform:
            case Platform.DISCORD:
                self.client.run(self.token, log_handler=None)
            case Platform.TELEGRAM:
                self.application.run_polling()

    async def run_async(self):
        match self.platform:
            case Platform.DISCORD:
                await self.client.start(self.token)
            case Platform.TELEGRAM:
                await self.application.initialize()
                await self.application.start()
                await self.application.updater.start_polling()
