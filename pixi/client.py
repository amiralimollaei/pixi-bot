from dataclasses import asdict
import asyncio
import json
import logging
import math
import os
import time

from .typing import AsyncPredicate, Optional
from .chatbot import AsyncChatbotInstance, CachedAsyncChatbotFactory
from .agents import AgentBase, RetrievalAgent
from .apis import AsyncGiphyAPI, AsyncWikimediaAPI
from .chatbot import AssistantPersona, PredicateCommand, PredicateTool
from .chatting import ChatMessage
from .database import DirectoryDatabase
from .enums import ChatRole, Messages, Platform
from .reflection import ReflectionAPI
from .addon import AddonManager

# constants

COMMAND_PREFIXES = ["!pixi", "!pix", "!p"]


# helper functions

def remove_prefixes(text: str):
    for prefix in COMMAND_PREFIXES:
        text = text.removeprefix(prefix)
    return text


class PixiClient:
    def __init__(
        self,
        platform: Platform,
        *,
        model: str,
        helper_model: str,
        api_url: str,
        persona_file: str = "persona.json",
        database_names: Optional[list[str]] = None,
        enable_tool_calls: bool = False,
        log_tool_calls: bool = False
    ):
        self.platform = platform
        self.persona = AssistantPersona.from_json(persona_file)
        self.api_url = api_url
        self.chatbot_factory = CachedAsyncChatbotFactory(
            bot=self,
            model=model,
            base_url=api_url,
            persona=self.persona,
            hash_prefix=platform,
            log_tool_calls=log_tool_calls,
        )
        self.reflection_api = ReflectionAPI(platform=platform, bot=None)
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
        if self.enable_tool_calls:
            self.init_mediawiki_tools(url="https://minecraft.wiki/", wiki_name="minecraft")
            self.init_mediawiki_tools(url="https://www.wikipedia.org/w/", wiki_name="wikipedia")
            # self.init_mediawiki_tools(url="https://mcdf.wiki.gg/", wiki_name="minecraft_discontinued_features")

        self.init_chatbot_commands()

        match platform:
            case Platform.DISCORD:
                self.init_discord()

            case Platform.TELEGRAM:
                self.init_telegram()

        self.addon_manager = AddonManager(self)
        self.addon_manager.load_addons()

    def register_tool(self, name: str, func, parameters: dict, description: Optional[str], predicate: Optional[AsyncPredicate] = None):
        if not self.enable_tool_calls:
            logging.warning("tried to register a tool, but tool calls are disabled")
            return

        self.chatbot_factory.register_tool(PredicateTool(
            name=name,
            func=func,
            parameters=parameters,
            description=description,
            predicate=predicate
        ))

    def register_command(self, name: str, func, field_name: str, description: str, predicate: Optional[AsyncPredicate] = None):
        self.chatbot_factory.register_command(PredicateCommand(
            name=name,
            func=func,
            field_name=field_name,
            description=description,
            predicate=predicate
        ))

    def create_agent_instance(self, agent: type[AgentBase], **agent_kwargs):
        return agent(model=self.helper_model, base_url=self.api_url, **agent_kwargs)
    
    async def register_slash_command(self, name: str, function, description: str | None = None):
        match self.platform:
            case Platform.DISCORD:
                import discord
                
                # Slash command: /reset
                @self.client.tree.command(name=name, description=description)
                async def slash_command(interaction: discord.Interaction):
                    await function(interaction)

            case Platform.TELEGRAM:
                import telegram
                from telegram.ext import ContextTypes, CommandHandler
                
                async def slash_command(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
                    message = update.message
                    await function(message)

                self.application.add_handler(CommandHandler(name, slash_command))

    async def send_command(self, instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
        assert reference.origin is not None

        delay_time = time.time() - instance.last_send_time
        instance.last_send_time = time.time()

        wait_time = max(0, (0.5 + (1.8 ** math.log2(1+len(value))) / 10) - delay_time)
        await self.reflection_api.send_reply(reference.origin, value, wait_time, should_reply = False)

    async def note_command(self, instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
        assert reference.origin is not None
        assert reference.instance_id is not None

        if instance.is_notes_visible:
            await self.reflection_api.send_reply(reference.origin, f"> note: {value}")

    async def react_command(self, instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
        assert reference.origin is not None
        reference_message = reference.origin

        try:
            await self.reflection_api.add_reaction(reference_message, value)
        except Exception:
            logging.exception(f"Failed to add reaction {value} to message {reference_message.id}")

    def init_chatbot_commands(self):
        self.chatbot_factory.register_command(PredicateCommand(
            name="send",
            field_name="message",
            func=self.send_command,
            description="sends a text as a distinct chat message, you may want to mention the user(s) in order to show that you're responding to them specifically if you are talking to multiple poeple at the same time (for clarity), you MUST use this command to send a response, otherwise the user WILL NOT SEE it and your response will be IGNORED."
        ))

        self.chatbot_factory.register_command(PredicateCommand(
            name="note",
            field_name="thoughts",
            func=self.note_command,
            description="annotates your thoughts, the user will not see these, it is completey private and only available to you, you Must do this before each message, thoughts should be at least 50 words"
        ))

        self.chatbot_factory.register_command(PredicateCommand(
            name="react",
            field_name="emoji",
            func=self.react_command,
            description="react with an emoji (presented in utf-8) to the current message that you are responding to, you may react to messages that are shocking or otherwise in need of immediate emotional reaction, you can send multiple reactions by using this command multuple times."
        ))

    async def __init_database_tools(self):
        if not self.enable_tool_calls:
            logging.warning("tried to initalize a database tool, but tool calls are disabled")
            self.database_tools_initalized.set()
            return

        await asyncio.gather(*(
            self.init_database_tool(database_name) for database_name in self.database_names
        ))
        self.database_tools_initalized.set()

    async def init_database_tool(self, database_name: str):
        if not self.enable_tool_calls:
            logging.warning("tried to initalize a database tool, but tool calls are disabled")
            return

        database_api = await DirectoryDatabase.from_directory(database_name)

        async def get_entry_as_str(entry_id: int):
            dataset_entry = await database_api.get_entry(entry_id)
            return json.dumps(asdict(dataset_entry), ensure_ascii=False)

        async def search_database(instance: AsyncChatbotInstance, reference: ChatMessage, keyword: str):
            return [asdict(match) for match in await database_api.search(keyword)]

        self.register_tool(
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

        async def query_database(instance: AsyncChatbotInstance, reference: ChatMessage, query: str, ids: str):
            if ids is None:
                return "no result: no id specified"

            agent: RetrievalAgent = self.create_agent_instance(
                agent=RetrievalAgent,
                context=await asyncio.gather(*[
                    get_entry_as_str(int(entry_id.strip())) for entry_id in ids.split(",")
                ])
            )
            return await agent.retrieve(query)

        self.register_tool(
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
        if not self.enable_tool_calls:
            logging.warning("tried to initalize a mediawiki tool, but tool calls are disabled")
            return

        wiki_api = AsyncWikimediaAPI(url)

        async def search_wiki(instance: AsyncChatbotInstance, reference: ChatMessage, keyword: str):
            return [asdict(search_result) for search_result in await wiki_api.search(keyword)]

        self.register_tool(
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

        async def query_wiki_content(instance: AsyncChatbotInstance, reference: ChatMessage, titles: str, query: str):
            if titles.split("|") is None:
                return "no result: no page specified"

            agent: RetrievalAgent = self.create_agent_instance(
                agent=RetrievalAgent,
                context=await asyncio.gather(*[
                    wiki_api.get_raw(t.strip()) for t in titles.split("|")
                ])
            )
            return await agent.retrieve(query)

        self.register_tool(
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
        if not self.enable_tool_calls:
            logging.warning("tried to initalize discord specific tools, but tool calls are disabled")
            return

        async def fetch_channel_history(instance: AsyncChatbotInstance, reference: ChatMessage, channel_id: str, n: str):
            channel = await self.client.fetch_channel(int(channel_id))
            messages = []
            # TODO: check channel type
            async for message in channel.history(limit=int(n)):  # type: ignore
                messages.append(dict(
                    from_user=self.reflection_api.get_sender_information(message).get("display_name", "Unknown"),
                    message_text=self.reflection_api.get_message_text(message)
                ))

            return messages[::-1]

        self.register_tool(
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
            async def search_gif(instance: AsyncChatbotInstance, reference: ChatMessage, query: str):
                logging.info(f"calling search_gif({query=})")
                assert self.giphy_api is not None
                resp: dict = await self.giphy_api.search(query, rating="pg", limit = 10)  # type: ignore
                data = resp.get("data")
                results = []
                if data is None:
                    logging.warning(f"No GIFs found for query: {query}")
                    return []
                for gif in data:
                    if id := gif.get("id"):
                        results.append(dict(
                            title=gif.get("title"),
                            rating=gif.get("rating"),
                            url=f"https://i.giphy.com/{id}.webp"
                        ))
                return results

            self.register_tool(
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
                description="searches the internet for the most relevent GIFs based on a query, to send a gif send the GIF's URL as a distinct chat message, the URL always starts with \"https://i.giphy/\""
            )

    async def notes_command(self, interaction):
        if not await self.reflection_api.is_dm_or_admin(interaction):
            await self.reflection_api.send_reply(interaction, "You must be a guild admin or use this in DMs.", ephemeral=True)
            return
        try:
            identifier = self.reflection_api.get_identifier_from_message(interaction)
            conversation = await self.get_conversation_instance(identifier)
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
        instance = await self.get_conversation_instance(identifier)  # make sure the instance is in memory before removing
        self.chatbot_factory.remove(identifier)
        logging.info(f"the conversation in {identifier} has been reset.")

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
        
        self.reflection_api = ReflectionAPI(platform=self.platform, bot=client)

        @client.event
        async def on_message(*args, **kwargs):
            return await self.on_message(*args, **kwargs)

        # Slash command: /reset
        @client.tree.command(name="reset", description="Reset the conversation.")
        async def reset_command(interaction: discord.Interaction):
            await self.reset_command(interaction)

        # Slash command: /notes
        @client.tree.command(name="notes", description="See pixi's thoughts")
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

        application = Application.builder().token(self.token).read_timeout(30).write_timeout(30).build()
        self.application = application
        
        self.reflection_api = ReflectionAPI(platform=self.platform, bot=application.bot)

        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('reset', reset))
        application.add_handler(CommandHandler('notes', notes))
        application.add_handler(MessageHandler(filters.TEXT, callback=on_message))
        application.add_handler(MessageHandler(filters.PHOTO, callback=on_message))
        application.add_handler(MessageHandler(filters.AUDIO, callback=on_message))

    async def get_conversation_instance(self, identifier: str) -> AsyncChatbotInstance:
        return await self.chatbot_factory.get(identifier)

    async def pixi_resp(self, instance: AsyncChatbotInstance, chat_message: ChatMessage, allow_ignore: bool = True):
        assert chat_message.origin
        message = chat_message.origin
        
        channel_id = self.reflection_api.get_message_channel_id(message)

        try:
            instance.add_message(chat_message)
            task = await instance.concurrent_channel_stream_call(
                channel_id=str(channel_id),
                reference_message=chat_message,
                allow_ignore=allow_ignore
            )
            while not task.done():
                await self.reflection_api.send_status_typing(message)
                await asyncio.sleep(3)
            noncall_result = await task
            #noncall_result = await instance.stream_call(reference_message=chat_message, allow_ignore=allow_ignore)
            if noncall_result:
                logging.warning(f"{noncall_result=}")
        except ReflectionAPI.Forbidden:
            logging.exception(f"Cannot send message in {instance.uuid}, permission denied.")
        except Exception:
            logging.exception(f"Unknown error while responding to a message in {instance.uuid}.")
            await self.reflection_api.send_reply(message, Messages.UNKNOWN_ERROR)

        responded = True  # TODO: track the command usage and check if the message is responded to
        if not responded:
            if allow_ignore:
                raise RuntimeError("there was no response to a message while ignoring a message is not allowed.")
            else:
                logging.warning("there was no response to the message while ignoring a message is allowed.")
        
        return responded

    async def pixi_resp_retry(self, chat_message: ChatMessage, num_retry: int = 3):
        """
        create a copy of all messages in the conversation instance and try to respond to the message.
        if the response fails, it will retry up to `num_retry` times.
        if the response is successful, it will save the conversation instance and return True.
        if the response fails after all retries, it will return False.
        """
        
        if not self.database_tools_initalized.is_set():
            await self.__init_database_tools()
            await self.database_tools_initalized.wait()
        
        async def rearrage_predicate(msg: ChatMessage):
            msg_channel_id = msg.metadata.get("channel_id") if msg.metadata else None
            current_channel_id = chat_message.metadata.get("channel_id") if chat_message.metadata else None
            
            if msg_channel_id is None or current_channel_id is None:
                return False
            return msg_channel_id == current_channel_id
        
        assert chat_message.origin
        message = chat_message.origin
        
        assert chat_message.instance_id
        identifier = chat_message.instance_id

        instance = await self.get_conversation_instance(identifier)
        instance.update_realtime(self.reflection_api.get_realtime_data(message))
        instance.set_rearrange_predicate(rearrage_predicate)
        
        for i in range(num_retry):
            messages_checkpoint = instance.get_messages().copy()
            try:
                ok = await self.pixi_resp(instance, chat_message)
            except Exception:
                logging.exception("There was an error in `pixi_resp`")
                ok = False
            if ok:
                instance.save()
                logging.debug("responded to a message and saved the conversation.")
                return True
            else:
                logging.warning(f"Retrying ({i}/{num_retry})")
                instance.set_messages(messages_checkpoint)

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
        convo = await self.chatbot_factory.get(convo_id)

        attached_images = await self.reflection_api.fetch_attachment_images(message)
        attached_audio = await self.reflection_api.fetch_attachment_audio(message)

        message_author = self.reflection_api.get_sender_information(message)

        metadata = dict(
            from_user=message_author
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

        # convert everything into `ChatMessage``
        role_message = ChatMessage(
            role=ChatRole.USER,
            content=message_text,
            metadata=metadata,
            images=attached_images,
            audio=attached_audio,
            # these properties are intended to be used internally and are NOT reload persistant
            instance_id=convo_id,
            origin=message
        )
        await self.pixi_resp_retry(role_message)

    def run(self):
        match self.platform:
            case Platform.DISCORD:
                assert self.token
                self.client.run(self.token, log_handler=None)
            case Platform.TELEGRAM:
                self.application.run_polling()

    async def run_async(self):
        match self.platform:
            case Platform.DISCORD:
                assert self.token
                await self.client.start(self.token)
            case Platform.TELEGRAM:
                await self.application.initialize()
                await self.application.start()
                assert self.application.updater
                await self.application.updater.start_polling()
