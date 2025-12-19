from dataclasses import asdict
import asyncio
import json
import logging
import ssl

from .typing import AsyncPredicate, Optional
from .chatbot import AsyncChatbotInstance, CachedAsyncChatbotFactory, PredicateCommand, PredicateTool
from .agents import AgentBase, RetrievalAgent
from .apis import AsyncTenorAPI, AsyncWikimediaAPI
from .caching import SUPPORTS_MEDIA_CACHING
from .chatting import ChatMessage
from .enums import ChatRole, Messages, Platform
from .reflection import ReflectionAPI, ReflectionMessageBase
from .addon import AddonManager
from .config import OpenAIAuthConfig, OpenAIEmbeddingModelConfig, OpenAILanguageModelConfig, PixiFeatures, IdFilter, DatasetConfig
from .database import AsyncEmbeddingDatabase, DirectoryDatabase


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
        auth: OpenAIAuthConfig,
        model: OpenAILanguageModelConfig,
        helper_model: OpenAILanguageModelConfig | None,
        embedding_model: OpenAIEmbeddingModelConfig | None,
        features: PixiFeatures = PixiFeatures.EnableToolCalling | PixiFeatures.EnableToolLogging,
        datasets: list[DatasetConfig] = [],
        environment_filter: IdFilter = IdFilter.allow(),
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Initalizing Pixi with feature set {features} and platform {platform}...")

        self.platform = platform

        self.auth = auth
        self.model = model
        self.helper_model = helper_model or model
        self.embedding_model = embedding_model
        self.features = features
        self.enable_tool_calls = PixiFeatures.EnableToolCalling in features
        self.log_tool_calls = PixiFeatures.EnableToolLogging in features
        self.datasets = []
        self.environment_filter = environment_filter
        
        if self.enable_tool_calls:
            self.datasets = [self.register_database_tool(d) for d in datasets]

        self.accept_images = PixiFeatures.EnableImageSupport in features
        self.accept_audio = PixiFeatures.EnableAudioSupport in features
        if (self.accept_images or self.accept_audio) and not SUPPORTS_MEDIA_CACHING:
            self.logger.warning("tried to accept audio/images, but media caching features are not available")
            self.accept_images = False
            self.accept_audio = False

        self.chatbot_factory = CachedAsyncChatbotFactory(
            parent=self,
            auth=self.auth,
            model=model,
            hash_prefix=platform,
            log_tool_calls=self.log_tool_calls,
        )

        self.reflection_api = ReflectionAPI(platform=platform)

        self.gif_api = None
        if PixiFeatures.EnableGIFSearch in features:
            try:
                self.gif_api = AsyncTenorAPI()
            except KeyError:
                self.logger.warning("TENOR_API_KEY is not set, TENOR API features will not be available.")

        self.__register_builtin_commands()
        
        # TODO: add configurable wikis
        if self.enable_tool_calls and PixiFeatures.EnableWikiSearch in features:
            self.register_mediawiki_tools(url="https://minecraft.wiki/", wiki_name="minecraft")
            self.register_mediawiki_tools(url="https://www.wikipedia.org/w/", wiki_name="wikipedia")
            # self.register_mediawiki_tools(url="https://mcdf.wiki.gg/", wiki_name="minecraft_discontinued_features")

        if platform == Platform.DISCORD and self.enable_tool_calls:
            self.__register_discord_specific_tools()

        self.__register_builtin_slash_commands()

        self.addon_manager = AddonManager(self)
        self.addon_manager.load_addons()

        self.reflection_api.register_on_message_event(self.on_message)

        self.logger.info(f"Pixi finised initalizing!")

    def register_tool(self, name: str, func, parameters: dict, description: Optional[str], predicate: Optional[AsyncPredicate] = None):
        if not self.enable_tool_calls:
            self.logger.warning("tried to register a tool, but tool calls are disabled, ignoring...")
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
        return agent(auth=self.auth, model=self.helper_model, log_tool_calls=self.log_tool_calls, **agent_kwargs)

    def register_slash_command(self, name: str, function, description: str | None = None):
        async def checked_function(message: ReflectionMessageBase):
            environment_id = message.environment_id
            if not self.is_environment_allowed(environment_id):
                self.logger.warning(
                    f"ignoring slash command in {environment_id} because it is not in the allowed places.")
                await message.send("This command is not allowed here.")
                return
            await function(message)
        self.reflection_api.register_slash_command(name, checked_function, description)

    async def typing_delay(self, message: ReflectionMessageBase, delay: float):
        delay_served = 0.0
        while delay_served < delay:
            await message.typing()
            await asyncio.sleep(3.0)
            delay_served += 3.0

    def __register_builtin_commands(self):
        async def send_command(instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
            if not value:
                return

            assert reference.origin is not None
            message: ReflectionMessageBase = reference.origin

            #wait_time = (1.8 ** math.log2(1+len(value))) * 0.1

            #await self.typing_delay(message, wait_time)
            await message.send(value)

        self.register_command(
            name="send",
            field_name="message",
            func=send_command,
            description="sends a text as a distinct chat message, you MUST use this command to send a response, otherwise the user WILL NOT SEE it and your response will be IGNORED."
        )
        if self.gif_api is not None:
            async def send_gif(instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
                if not value:
                    return
                assert self.gif_api is not None

                assert reference.origin is not None
                message: ReflectionMessageBase = reference.origin
                
                resp: dict = await self.gif_api.search(value, locale="en_us", limit=1)  # type: ignore
                results = []
                for gif_content in resp.get("results", []):
                    results.append(dict(
                        content_description=gif_content.get("content_description", ""),
                        content_rating=gif_content.get("content_rating", ""),
                        url=gif_content.get("media", [])[0].get("gif", {}).get("url", "")
                    ))
                if results:
                    await message.send(results[0]["url"])

            self.register_command(
                name="send_gif",
                field_name="gif description",
                func=send_gif,
                description="sends a gif as a distinct chat message, it automatically finds a gif based on the description. gif description must be in English."
            )

        async def note_command(instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
            assert reference.origin is not None
            message: ReflectionMessageBase = reference.origin

            if instance.is_notes_visible:
                await message.send(f"> thoughts: {value}")

        self.register_command(
            name="note",
            field_name="thoughts",
            func=note_command,
            description="annotates your thoughts, the user will not see these, it is completey private and only available to you, you Must do this before each message, thoughts should be at least 50 words"
        )

        async def react_command(instance: AsyncChatbotInstance, reference: ChatMessage, value: str):
            assert reference.origin is not None
            message: ReflectionMessageBase = reference.origin

            try:
                await message.add_reaction(value)
            except Exception:
                self.logger.exception(f"Failed to add reaction {value} to message {message.id}")

        self.register_command(
            name="react",
            field_name="emoji",
            func=react_command,
            description="react with an emoji (presented in utf-8) to the current message that you are responding to, you may react to messages that are shocking or otherwise in need of immediate emotional reaction, you can send multiple reactions by using this command multuple times."
        )

    def register_database_tool(self, dataset_config: DatasetConfig) -> DirectoryDatabase | None:
        if not self.enable_tool_calls:
            self.logger.warning("tried to initalize a database tool, but tool calls are disabled")
            return
        
        database_name = dataset_config.name
        database_api = DirectoryDatabase.from_directory(dataset_config.name)

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

            if self.embedding_model:
                embedding_database = AsyncEmbeddingDatabase(self.auth, self.embedding_model)
                entries = await asyncio.gather(*[
                    database_api.get_entry(int(entry_id.strip())) for entry_id in ids.split(",")
                ])
                for entry in entries:
                    await embedding_database.add_document(entry.content, entry.title, entry.id)
                query_embed = await embedding_database.embed(query)
                matches = [
                    asdict(doc_match)
                    for doc_match in embedding_database.search(query_embed)  # pyright: ignore[reportArgumentType]
                ]
                return matches
            else:
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
            description=f"fetch and retrieve relevent information from the content of the {database_name} database based on a query."
        )
        return database_api

    def register_mediawiki_tools(self, url: str, wiki_name: str):
        if not self.enable_tool_calls:
            self.logger.warning("tried to initalize a mediawiki tool, but tool calls are disabled")
            return

        wiki_api = AsyncWikimediaAPI(url)

        async def fetch_wiki_page(title: str) -> tuple[str, str]:
            page_content, title = await wiki_api.get_plaintext(title.strip())
            return (page_content, title)

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
            if not titles:
                return "no result: no page specified"
            if (_titles := titles.split("|")) is None:
                return "no result: no page specified"

            context = await asyncio.gather(*[
                fetch_wiki_page(t) for t in _titles
            ])

            if self.embedding_model:
                embedding_database = AsyncEmbeddingDatabase(self.auth, self.embedding_model)
                for i, (page, title) in enumerate(context):
                    await embedding_database.add_document(page, title, i)
                query_embed = await embedding_database.embed(query)
                matches = [
                    asdict(doc_match)
                    for doc_match in embedding_database.search(query_embed)  # pyright: ignore[reportArgumentType]
                ]
                return matches
            else:
                agent = self.create_agent_instance(
                    agent=RetrievalAgent,
                    context=[page for page, title in context]
                )
                return await agent.execute_query(query)

        self.register_tool(
            name=f"query_wiki_content_{wiki_name}",
            func=query_wiki_content,
            parameters=dict(
                type="object",
                properties=dict(
                    query=dict(
                        type="string",
                        description=f"A statement that is searched inside the content of the wiki, it should clearly name what you're looking for, example: \"how to craft an arrow?\" not \"how to craft it\" and not \"craft\"",
                    ),
                    titles=dict(
                        type="string",
                        description=f"Page titles to fetch and query information from, seperated by a delimiter character: `|`. use `search_wiki_{wiki_name}` to optain page titles based a search term.",
                    ),
                ),
                required=["query", "titles"],
                additionalProperties=False
            ),
            description=f"fetch wiki content and retrieve relevent information from them based on a query."
        )

    def __register_discord_specific_tools(self):
        if not self.enable_tool_calls:
            self.logger.warning("tried to initalize discord specific tools, but tool calls are disabled")
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

    def __register_builtin_slash_commands(self):
        async def notes_slash_command(message: ReflectionMessageBase):
            if not await self.reflection_api.is_dm_or_admin(message):
                await message.send("You must be a guild admin or use this in DMs.")
                return
            try:
                environment_id = message.environment_id
                conversation = await self.get_conversation_instance(environment_id)
                is_notes_visible = conversation.toggle_notes()
                notes_message = "Notes are now visible." if is_notes_visible else "Notes are no longer visible"
                await message.send(notes_message)
            except Exception:
                self.logger.exception(f"Failed to toggle notes")
                await message.send("Failed to toggle notes.")

        async def reset_slash_command(message: ReflectionMessageBase):
            if not await self.reflection_api.is_dm_or_admin(message):
                await message.send("You must be a guild admin or use this in DMs.")
                return

            environment_id = message.environment_id

            self.chatbot_factory.remove(environment_id)
            self.logger.info(f"the conversation in {environment_id} has been reset.")

            await message.send("Wha- Where am I?!")

        if self.platform == Platform.TELEGRAM:
            # for some reason event handlers in telegram are order dependent, meaning we should
            # run register_on_message_event after all slash commands are registered or else the
            # slash commands will not work.
            async def start_command(message: ReflectionMessageBase):
                await message.send("Hiiiii, how's it going?")

            self.register_slash_command(name="start", function=start_command)

        self.register_slash_command(
            name="reset",
            function=reset_slash_command,
            description="Reset the conversation."
        )

        self.register_slash_command(
            name="notes",
            function=notes_slash_command,
            description="See pixi's thoughts"
        )

    async def get_conversation_instance(self, identifier: str) -> AsyncChatbotInstance:
        return await self.chatbot_factory.get_or_create(identifier)

    async def pixi_resp(self, instance: AsyncChatbotInstance, chat_message: ChatMessage, allow_ignore: bool = True):
        assert chat_message.origin
        message: ReflectionMessageBase = chat_message.origin

        channel_id = message.environment.chat_id

        try:
            instance.add_message(chat_message)
            # concurrent_channel_stream_call handles overlapping requests automatically
            # killing tasks that are not done and restarting the request every time untill
            # one task finishes before the next request
            #
            # this way we can handle situations where the user is sending messages too quickly
            # with less tokens, but may increase response time, and killing tasks may result in
            # lost progress and http errors.
            #
            # TODO: find a solution to the above
            task = await instance.concurrent_channel_stream_call(
                channel_id=str(channel_id),
                reference_message=chat_message,
                allow_ignore=allow_ignore
            )
            while not task.done():
                try:
                    await message.typing()
                    await asyncio.sleep(3)
                except ssl.SSLError:
                    self.logger.warning("SSLError accrued while sending typing status")
                except Exception:
                    self.logger.exception("an error accrued while sending typing status")
            noncall_result = await task
            if noncall_result:
                self.logger.warning(f"{noncall_result=}")
        except Exception:
            self.logger.exception(f"Unknown error while responding to a message in {instance.id}.")
            await message.send(Messages.UNKNOWN_ERROR)

        responded = True  # TODO: track the command usage and check if the message is responded to
        if not responded:
            if not allow_ignore:
                raise RuntimeError("there was no response to a message while ignoring a message is not allowed.")
            else:
                self.logger.warning("there was no response to the message while ignoring a message is allowed.")

        return responded

    async def pixi_resp_retry(self, chat_message: ChatMessage, num_retry: int = 3):
        """
        create a copy of all messages in the conversation instance and try to respond to the message.
        if the response fails, it will retry up to `num_retry` times.
        if the response is successful, it will save the conversation instance and return True.
        if the response fails after all retries, it will return False.
        """

        async def rearrage_predicate(msg: ChatMessage):
            msg_channel_id = msg.origin.environment.chat_id if msg.origin else None
            current_channel_id = chat_message.origin.environment.chat_id if chat_message.origin else None

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
                self.logger.exception("There was an error in `pixi_resp`")
                ok = False
            if ok:
                instance.save()
                self.logger.debug("responded to a message and saved the conversation.")
                return True
            else:
                self.logger.warning(f"Retrying ({i}/{num_retry})")
                instance.set_messages(messages_checkpoint)

    def is_environment_allowed(self, identifier: str) -> bool:
        """
        Check if the environment identifier is allowed to be processed.
        """
        return self.environment_filter.is_allowed(identifier)

    async def on_message(self, message: ReflectionMessageBase):
        # we should not process our own messages again
        if self.reflection_api.is_message_from_the_bot(message):
            return

        message_text = message.content

        # Check if the message is a command, a reply to the bot, a DM, or mentions the bot
        bot_mentioned = self.reflection_api.is_bot_mentioned(message)
        is_keyword_present = False
        for keyword in COMMAND_KEYWORDS:
            if keyword in message_text.lower():
                is_keyword_present = True
                break
        is_prefixed = message_text.lower().startswith(tuple(COMMAND_PREFIXES))
        environment_id = message.environment_id

        if not (message.is_inside_dm() or bot_mentioned or is_prefixed or is_keyword_present):
            return

        if not self.is_environment_allowed(environment_id):
            self.logger.warning(f"ignoring message in {environment_id} because it's not in an allowed environment.")
            return

        if is_prefixed:
            message_text = remove_prefixes(message_text)

        instance = await self.chatbot_factory.get_or_create(environment_id)

        attached_images = None
        if self.accept_images:
            attached_images = await message.fetch_images()
        attached_audio = None
        if self.accept_audio:
            attached_audio = await message.fetch_audio()

        message_author = asdict(message.author)

        metadata = dict(
            from_user=message_author
        )

        # check if the message is a reply to a bot message
        reply_message = await message.fetch_refrences()
        if reply_message is not None:
            reply_message_text = remove_prefixes(reply_message.content)
            # if the reply is to the last message that is sent by the bot, we don't need to do anything.
            reply_optimization = -1
            instance_messages = instance.get_messages()
            matching_messages = [
                msg.content for msg in instance_messages if msg.content is not None and reply_message_text in msg.content]
            if matching_messages:
                if instance_messages[-1].content in matching_messages:
                    reply_optimization = 2
                else:
                    reply_optimization = 1
            if reply_optimization == 2:
                # completely ignore reply context
                self.logger.debug(f"completely ignore reply context for {environment_id=}")
            elif reply_message and self.reflection_api.is_message_from_the_bot(reply_message):
                if reply_optimization == 1:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": "[YOU]",
                        "partial_content": reply_message_text[:64]
                    }
                else:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": "[YOU]",
                        "message": reply_message_text
                    }
            else:
                if reply_optimization == 1:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": asdict(reply_message.author),
                        "partial_message": reply_message_text[:64]
                    }
                else:
                    metadata["in_reply_to"] = {  # pyright: ignore[reportArgumentType]
                        "from": asdict(reply_message.author),
                        "message": reply_message_text
                    }

        # convert everything into `ChatMessage`
        role_message = ChatMessage(
            role=ChatRole.USER,
            content=message_text,
            metadata=metadata,
            images=attached_images,
            audio=attached_audio,
            # the following properties are intended to be used internally and are NOT reload persistant
            instance_id=environment_id,
            origin=message
        )
        await self.pixi_resp_retry(role_message)

    def run(self):
        self.reflection_api.run()
