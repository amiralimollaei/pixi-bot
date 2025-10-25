from dataclasses import asdict
import asyncio
import json
import logging
import math
import time

from .typing import AsyncPredicate, Optional
from .chatbot import AsyncChatbotInstance, CachedAsyncChatbotFactory
from .agents import AgentBase, RetrievalAgent
from .apis import AsyncTenorAPI, AsyncWikimediaAPI
from .chatbot import AssistantPersona, PredicateCommand, PredicateTool
from .chatting import ChatMessage
from .database import DirectoryDatabase
from .enums import ChatRole, Messages, Platform
from .reflection import ReflectionAPI
from .addon import AddonManager

# constants

COMMAND_PREFIXES = ["!pixi", "!pix", "!p"]
COMMAND_KEYWORDS = ["pixi", "پیکسی"]


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
        log_tool_calls: bool = False,
        allowed_places: Optional[list[str]] = None,
        accept_images: bool = True,
        accept_audio: bool = True,
    ):
        self.platform = platform
        self.persona = AssistantPersona.from_json(persona_file)
        self.api_url = api_url
        self.chatbot_factory = CachedAsyncChatbotFactory(
            parent=self,
            model=model,
            base_url=api_url,
            persona=self.persona,
            hash_prefix=platform,
            log_tool_calls=log_tool_calls,
        )
        self.helper_model = helper_model
        self.enable_tool_calls = enable_tool_calls

        self.allowed_places = allowed_places or []

        self.accept_images = accept_images
        self.accept_audio = accept_audio

        self.database_names = database_names or []
        self.database_tools_initalized = asyncio.Event()

        self.reflection_api = ReflectionAPI(platform=platform)

        self.gif_api = None

        try:
            self.gif_api = AsyncTenorAPI()
        except KeyError:
            logging.warning("TENOR_API_KEY is not set, TENOR API features will not be available.")

        # try:
        #    self.gif_api = AsyncGiphyAPI()
        # except KeyError:
        #    logging.warning("GIPHY_API_KEY is not set, GIPHY API features will not be available.")

        # TODO: add configurable wikis
        if self.enable_tool_calls:
            self.init_mediawiki_tools(url="https://minecraft.wiki/", wiki_name="minecraft")
            # self.init_mediawiki_tools(url="https://www.wikipedia.org/w/", wiki_name="wikipedia")
            # self.init_mediawiki_tools(url="https://mcdf.wiki.gg/", wiki_name="minecraft_discontinued_features")

        self.init_chatbot_commands()

        if platform == Platform.DISCORD and self.enable_tool_calls:
            self.init_discord_specific_tools()

        if platform == Platform.TELEGRAM:
            # for some reason handlers in telegram are order dependent, meaning we should add MessageHandler
            # after all slash commands are registered or else the slash commands will not work.
            self.register_telegram_start_command()

        self.register_slash_command(
            name="reset",
            function=self.reset_command,
            description="Reset the conversation."
        )

        self.register_slash_command(
            name="notes",
            function=self.notes_command,
            description="See pixi's thoughts"
        )

        self.addon_manager = AddonManager(self)
        self.addon_manager.load_addons()
        
        self.reflection_api.register_on_message_event(self.on_message)

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

    def create_agent_instance(self, agent: type[AgentBase], **agent_kwargs) -> AgentBase:
        return agent(model=self.helper_model, base_url=self.api_url, **agent_kwargs)

    def register_slash_command(self, name: str, function, description: str | None = None):
        async def checked_function(interaction):
            convo_id = self.reflection_api.get_identifier_from_message(interaction)
            if not self.is_identifier_allowed(convo_id):
                logging.warning(f"ignoring slash command in {convo_id} because it is not in the allowed places.")
                await self.reflection_api.send_reply(interaction, "This command is not allowed in this place.", ephemeral=True)
                return
            await function(interaction)
        self.reflection_api.register_slash_command(name, checked_function, description)

    async def send_command(self, instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
        if not value:
            return

        assert reference.origin is not None

        delay_time = time.time() - instance.last_send_time
        instance.last_send_time = time.time()

        wait_time = max(0, (0.5 + (1.8 ** math.log2(1+len(value))) / 10) - delay_time)
        await self.reflection_api.send_reply(reference.origin, value, wait_time, should_reply=False)

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
            description="sends a text as a distinct chat message, you MUST use this command to send a response, otherwise the user WILL NOT SEE it and your response will be IGNORED."
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

            agent = self.create_agent_instance(
                agent=RetrievalAgent,
                context=await asyncio.gather(*[
                    get_entry_as_str(int(entry_id.strip())) for entry_id in ids.split(",")
                ])
            ) 
            return await agent.execute_query(query)

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

            agent = self.create_agent_instance(
                agent=RetrievalAgent,
                context=await asyncio.gather(*[
                    wiki_api.get_raw(t.strip()) for t in titles.split("|")
                ])
            )  # pyright: ignore[reportAssignmentType]
            return await agent.execute_query(query)

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

    def init_discord_specific_tools(self):
        if not self.enable_tool_calls:
            logging.warning("tried to initalize discord specific tools, but tool calls are disabled")
            return

        async def fetch_channel_history(instance: AsyncChatbotInstance, reference: ChatMessage, channel_id: str, n: int):
            return await self.reflection_api.fetch_channel_history(int(channel_id), n=n)

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

        if self.gif_api is not None:
            async def search_gif(instance: AsyncChatbotInstance, reference: ChatMessage, query: str, locale: str):
                assert self.gif_api is not None
                resp: dict = await self.gif_api.search(query, locale=locale, limit=10)  # type: ignore
                results = []
                for gif_content in resp.get("results", []):
                    results.append(dict(
                        content_description=gif_content.get("content_description", ""),
                        content_rating=gif_content.get("content_rating", ""),
                        url=gif_content.get("media", [])[0].get("gif", {}).get("url", "")
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
                            "description": "The search string.",
                        },
                        "locale": {
                            "type": "string",
                            "description": "specify default language to interpret search string; xx is ISO 639-1 language code, _YY (optional) is 2-letter ISO 3166-1 country code",
                        },
                    },
                    required=["query", "locale"],
                    additionalProperties=False
                ),
                description="searches the internet for the most relevent GIFs based on a query, to send a gif send the GIF's URL as a distinct chat message."
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

        self.chatbot_factory.remove(identifier)
        logging.info(f"the conversation in {identifier} has been reset.")

        await self.reflection_api.send_reply(interaction, "Wha- Where am I?!")

    def register_telegram_start_command(self):
        async def start_command(message):
            await self.reflection_api.send_reply(message, "Hiiiii, how's it going?")

        self.register_slash_command(name="start", function=start_command)

    async def get_conversation_instance(self, identifier: str) -> AsyncChatbotInstance:
        return await self.chatbot_factory.get_or_create(identifier)

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
            # noncall_result = await instance.stream_call(reference_message=chat_message, allow_ignore=allow_ignore)
            if noncall_result:
                logging.warning(f"{noncall_result=}")
        except Exception:
            logging.exception(f"Unknown error while responding to a message in {instance.id}.")
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

        messages_checkpoint = instance.get_messages().copy()
        for i in range(num_retry):
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

    def is_identifier_allowed(self, identifier: str) -> bool:
        """
        Check if the identifier is in the allowed places.
        If allowed places are not set, return True.
        """
        return not self.allowed_places or identifier in self.allowed_places

    async def on_message(self, message):
        # we should not process our own messages again
        if self.reflection_api.is_message_from_the_bot(message):
            return

        message_text = self.reflection_api.get_message_text(message)

        # Check if the message is a command, a reply to the bot, a DM, or mentions the bot
        bot_mentioned = self.reflection_api.is_bot_mentioned(message)
        is_keyword_present = False
        for keyword in COMMAND_KEYWORDS:
            if keyword in message_text.lower():
                is_keyword_present = True
                break
        is_prefixed = message_text.lower().startswith(tuple(COMMAND_PREFIXES))
        is_inside_dm = self.reflection_api.is_inside_dm(message)
        convo_id = self.reflection_api.get_identifier_from_message(message)

        if not (is_inside_dm or bot_mentioned or is_prefixed or is_keyword_present):
            return

        if not self.is_identifier_allowed(convo_id):
            logging.warning(f"ignoring message in {convo_id} because it is not in the allowed places.")
            return

        if is_prefixed:
            message_text = remove_prefixes(message_text)

        convo = await self.chatbot_factory.get_or_create(convo_id)

        attached_images = None
        if self.accept_images:
            attached_images = await self.reflection_api.fetch_attachment_images(message)
        attached_audio = None
        if self.accept_audio:
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
        self.reflection_api.run()