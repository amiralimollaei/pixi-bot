import asyncio
import json
import logging
import ssl
from dataclasses import asdict, dataclass
from typing import Any, Callable, Coroutine, Optional

import httpx
import openai

from .addon import AddonManager
from .agents import AgentBase, RetrievalAgent
from .apis import AsyncTenorAPI, AsyncWikimediaAPI
from .caching import SUPPORTS_MEDIA_CACHING
from .chatting import (ActionContext, AsyncChatbotInstance,
                       ChatbotInstanceRegistry, AsyncTool, ToolContext)
from .model.chatting.callbacks import AsyncAction, Predicate
from .model.config import (DatasetConfig, IdFilter, MediaWikiConfig,
                           NewsConfig, OpenAIAuthConfig,
                           OpenAIEmbeddingModelConfig,
                           OpenAILanguageModelConfig, PixiFeatures)
from .model.enums import ChatRole, Platform
from .model.storage.message import ChatMessageMeta
from .rag.client import AsyncRAGClient
from .reflection import AbstractMessage, ReflectionAPI
from .storage.database import DirectoryDatabase
from .utils import format_time_later

# constants

SUMMON_KEYWORDS = ["pixi", "پیکسی"]


# helper functions

def remove_prefixes(text: str):
    text = text.strip()
    for keyword in SUMMON_KEYWORDS:
        for i in range(len(keyword)-1):
            text = text.removeprefix("!" + keyword[:len(keyword)-i])
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
        features: PixiFeatures = PixiFeatures.default(),
        datasets: list[DatasetConfig] = [],
        wikis: list[MediaWikiConfig] = [],
        environment_filter: IdFilter = IdFilter.allow(),
        news_config: Optional[NewsConfig] = None,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Initalizing Pixi with feature set {features} and platform {platform}...")

        self.platform = platform

        self.auth = auth
        self.model = model
        self.helper_model = helper_model or model
        self.embedding_model = embedding_model
        self.features = features
        self.news_config = news_config
        self.pre_startup_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []
        self.post_startup_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []

        # Verify models and API connectivity at startup
        self.register_pre_startup_hook(self.verify_models)

        # Pre-Load all the instances after startup
        self.register_post_startup_hook(self.preload_instances)

        self.enable_tool_calls = PixiFeatures.ToolCalling in features
        self.log_tool_calls = PixiFeatures.ToolLogging in features
        self.datasets = []
        self.environment_filter = environment_filter

        self.accept_images = PixiFeatures.ImageSupport in features
        self.accept_audio = PixiFeatures.AudioSupport in features
        if (self.accept_images or self.accept_audio) and not SUPPORTS_MEDIA_CACHING:
            self.logger.warning("tried to accept audio/images, but media caching features are not available")
            self.accept_images = False
            self.accept_audio = False

        ChatbotInstanceRegistry.init(hash_prefix = platform, bot = self)

        self.reflection_api = ReflectionAPI(platform=platform)

        self.gif_api = None
        if PixiFeatures.GIFSearch in features:
            try:
                self.gif_api = AsyncTenorAPI()
            except KeyError:
                self.logger.warning("TENOR_API_KEY is not set, TENOR API features will not be available.")

        self.__register_builtin_actions()

        if self.enable_tool_calls and datasets:
            self.logger.info(f"registering {len(datasets)} dataset(s):")
            for dataset_config in datasets:
                self.logger.info(f" - {dataset_config.name}")
                self.datasets.append(self.register_database_tool(dataset_config))

        if self.enable_tool_calls and PixiFeatures.WikiSearch in features and wikis:
            self.logger.info(f"registering {len(wikis)} wiki(s):")
            for wiki_config in wikis:
                self.logger.info(f" - {wiki_config.name}: {wiki_config.url}")
                self.register_mediawiki_tools(url=wiki_config.url, wiki_name=wiki_config.name)

        if platform == Platform.DISCORD and self.enable_tool_calls:
            self.__register_discord_specific_tools()

        self.__register_builtin_slash_commands()

        self.logger.info(f"loading addons...")
        self.addon_manager = AddonManager(self)
        self.addon_manager.load_addons()

        self.reflection_api.register_on_message_event(self.on_message)

        self.logger.info(f"Pixi finished initalizing!")

    async def preload_instances(self):
        self.logger.info("Pre-Loading all guilds instances...")
        for guild in await self.reflection_api.get_available_guilds():
            instance_id = f"forum#{guild.id}"
            self.logger.info(f" - \"{guild.name}\" (members: {guild.member_count})")
            self.get_chatbot_instance(instance_id)

    async def verify_models(self):
        """
        Verifies that the configured models exist on the API server and that the API is reachable.
        Logs a warning for any configured model IDs not found in the API's model list.
        Raises RuntimeError if the API is unreachable.
        """
        self.logger.info(f"Verifying API connectivity and model availability at {self.auth.base_url}...")

        try:
            session = openai.OpenAI(
                api_key=self.auth.api_key,
                base_url=self.auth.base_url,
                http_client=httpx.Client(trust_env=False),
            )
            models_page = session.models.list()
            available_models = {model.id for model in models_page}
            if available_models:
                self.logger.info(f"Found {len(available_models)} model(s) available:")
                for model in available_models:
                    self.logger.info(" - " + model)
            else:
                raise RuntimeError("No model available on the API server.")

            # Collect all configured model IDs
            configured_models: dict[str, str] = {}
            configured_models["main"] = self.model.id
            if self.helper_model:
                configured_models["helper"] = self.helper_model.id
            if self.embedding_model:
                configured_models["embedding"] = self.embedding_model.id

            for role, model_id in configured_models.items():
                if model_id not in available_models:
                    raise RuntimeError(
                        f"{role} model \"{model_id}\" was not found in the list of available models on the API server.")

        except openai.APIConnectionError as e:
            raise RuntimeError(
                f"Failed to connect to API at {self.auth.base_url}: {e}"
            ) from e
        except openai.AuthenticationError as e:
            raise RuntimeError(
                f"Failed to authenticate to API at {self.auth.base_url}: {e}"
            ) from e
        except openai.APIError as e:
            self.logger.warning(
                f"API responded with an error when listing models (status={e.code}), "
                "model verification will be skipped. This is expected for some OpenAI-compatible backends."
            )

    def register_tool(self, name: str, func, parameters: dict, description: Optional[str], predicate: Optional[Predicate] = None):
        if not self.enable_tool_calls:
            self.logger.warning("tried to register a tool, but tool calls are disabled, ignoring...")
            return

        ChatbotInstanceRegistry.register_tool(AsyncTool(
            name=name,
            function=func,
            parameters=parameters,
            description=description,
            predicate=predicate
        ))

    def register_action(self, name: str, function, field_name: str, description: str, predicate: Optional[Predicate] = None, is_visible: bool = True):
        ChatbotInstanceRegistry.register_action(AsyncAction(
            name=name,
            function=function,
            field_name=field_name,
            description=description,
            is_visible=is_visible,
            predicate=predicate,
        ))

    def create_agent_instance[A: AgentBase](self, agent_cls: type[A], **agent_kwargs) -> A:
        return agent_cls(auth=self.auth, model=self.helper_model, log_tool_calls=self.log_tool_calls, **agent_kwargs)

    def register_slash_command(self, name: str, function, description: str | None = None):
        async def checked_function(message: AbstractMessage):
            environment_id = message.environment_id
            if not self.is_environment_allowed(environment_id):
                self.logger.warning(
                    f"ignoring slash command in {environment_id} because it is not in the allowed places.")
                await message.send("This command is not allowed here.")
                return
            await function(message)
        self.reflection_api.register_slash_command(name, checked_function, description)

    async def typing_delay(self, message: AbstractMessage, delay: float):
        delay_served = 0.0
        while delay_served < delay:
            await message.typing()
            await asyncio.sleep(3.0)
            delay_served += 3.0

    def __register_builtin_actions(self):
        @dataclass(frozen=True)
        class ScheduleData:
            action: str
            value: str
            delay: float
            id: str

        async def schedule_action(ctx: ActionContext, value: str):
            if not value:
                return
            if ctx.reference_message is None:
                self.logger.error("reference_message is None")
                return
            if ctx.parent_instance is None:
                self.logger.error("parent_instance is None")
                return

            try:
                schedule_data = ScheduleData(**json.loads(value))
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                self.logger.exception(f"Invalid schedule JSON: {e}")
                return

            if not schedule_data.action or not schedule_data.value or schedule_data.delay is None or not schedule_data.id:
                self.logger.error("Schedule JSON must include 'action', 'value', 'delay', and 'id' fields.")
                return

            if not isinstance(schedule_data.delay, (int, float)) or schedule_data.delay <= 0:
                self.logger.error("'delay' must be a positive number.")
                return

            instance = ctx.parent_instance

            if instance.schedule_action(
                action=f"[{schedule_data.action}: {schedule_data.value}]",
                action_context=ctx,
                id=schedule_data.id,
                delay=schedule_data.delay
            ):
                self.logger.info(f"scheduled action for {format_time_later(schedule_data.delay)}: {value}")
            else:
                self.logger.info(f"schedule action failed: {value}")

        self.register_action(
            name="schedule",
            field_name="json",
            function=schedule_action,
            description="schedules an action to be executed later, the value for this action is a json with the following schema: {\"action\": <action-name>, \"value\": <action-value>, \"delay\": <delay-in-seconds>, \"id\": <unique-number>}"
        )

        async def cancel_schedule_action(ctx: ActionContext, value: str):
            if not value or ctx.reference_message is None:
                return
            assert ctx.reference_message.origin is not None
            message: AbstractMessage = ctx.reference_message.origin

            schedule_id = value.strip()
            if not schedule_id:
                self.logger.error("Model did not provide a schedule id to cancel.")
                return

            if ctx.parent_instance and ctx.parent_instance.cancel_schedule(schedule_id):
                self.logger.info(f"Cancelled the schedule with id '{schedule_id}'.")
            else:
                self.logger.info(f"No schedule found with id '{schedule_id}'.")

        self.register_action(
            name="cancel_schedule",
            field_name="id",
            function=cancel_schedule_action,
            description="cancels a previously scheduled action by its id (the ID for each schedule should be a unique number)"
        )

        async def send_action(ctx: ActionContext, value: str):
            if not value or ctx.reference_message is None:
                return
            assert ctx.reference_message.origin is not None
            message: AbstractMessage = ctx.reference_message.origin

            # wait_time = (1.8 ** math.log2(1+len(value))) * 0.1
            # await self.typing_delay(message, wait_time)
            await message.send(value)

        self.register_action(
            name="send",
            field_name="message",
            function=send_action,
            description="sends a message in the current chat"
        )
        if self.gif_api is not None:
            async def send_gif_action(ctx: ActionContext, value: str):
                if not value or ctx.reference_message is None:
                    return
                assert ctx.reference_message.origin is not None
                message: AbstractMessage = ctx.reference_message.origin

                assert self.gif_api is not None
                resp: dict = await self.gif_api.search(value, locale="en_us", limit=1)  # type: ignore
                results = []
                for gif_content in resp.get("results", []):
                    results.append(dict(
                        content_description=gif_content.get("content_description", ""),
                        content_rating=gif_content.get("content_rating", ""),
                        url=gif_content.get("media", [{}])[0].get("gif", {}).get("url", "")
                    ))
                if results:
                    await message.send(results[0]["url"])

            self.register_action(
                name="send_gif",
                field_name="gif description",
                function=send_gif_action,
                description="sends a gif in the current chat, the gif is chosen based on the provided description (description must be in English)"
            )

        async def note_action(ctx: ActionContext, value: str):
            if not value or ctx.reference_message is None:
                return
            assert ctx.reference_message.origin is not None
            message: AbstractMessage = ctx.reference_message.origin

            if ctx.parent_instance and ctx.parent_instance.is_notes_visible:
                await message.send(f"> thoughts: {value}")

        self.register_action(
            name="note",
            field_name="thoughts",
            function=note_action,
            description="annotates your thoughts, the user will not see these, it is completey private and only available to you, you must do this before each message, thoughts should be at least 50 words",
            is_visible=False,
        )

        async def react_action(ctx: ActionContext, value: str):
            if not value or ctx.reference_message is None:
                return
            assert ctx.reference_message.origin is not None
            message: AbstractMessage = ctx.reference_message.origin

            try:
                await message.add_reaction(value)
            except Exception:
                self.logger.exception(f"Failed to add reaction {value} to message {message.id}")

        self.register_action(
            name="react",
            field_name="emoji",
            function=react_action,
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
            return json.dumps(asdict(dataset_entry), ensure_ascii=False, indent=3)

        async def search_database(ctx: ToolContext, keyword: str):
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

        async def query_database(ctx: ToolContext, query: str, ids: str):
            if ids is None:
                return "no result: no id specified"

            if self.embedding_model:
                rag = AsyncRAGClient(self.auth, self.embedding_model)
                entries = await asyncio.gather(*[
                    database_api.get_entry(int(entry_id.strip())) for entry_id in ids.split(",")
                ])
                for entry in entries:
                    await rag.add_document(entry.content, entry.title, entry.id)
                query_embed = await rag.embed(query)
                matches = [
                    asdict(doc_match)
                    for doc_match in rag.search(query_embed)  # pyright: ignore[reportArgumentType]
                ]
                return matches
            else:
                agent = self.create_agent_instance(
                    agent_cls=RetrievalAgent,
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

        async def search_wiki(ctx: ToolContext, keyword: str):
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

        async def query_wiki_content(ctx: ToolContext, titles: str, query: str):
            if not titles:
                return "no result: no page specified"

            _titles = [t for t in titles.split("|") if t]
            if not _titles:
                return "no result: no page specified"

            context = await asyncio.gather(*[
                fetch_wiki_page(t) for t in _titles
            ])

            if self.embedding_model:
                rag = AsyncRAGClient(self.auth, self.embedding_model)
                for i, (page, title) in enumerate(context):
                    await rag.add_document(page, title, i)
                query_embed = await rag.embed(query)
                matches = [
                    asdict(doc_match)
                    for doc_match in rag.search(query_embed)  # pyright: ignore[reportArgumentType]
                ]
                return matches
            else:
                agent = self.create_agent_instance(
                    agent_cls=RetrievalAgent,
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

        async def fetch_channel_history(ctx: ToolContext, channel_id: str, n: int):
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
        async def notes_slash_command(message: AbstractMessage):
            if not await self.reflection_api.is_dm_or_admin(message):
                await message.send("You must be a guild admin or use this in DMs.")
                return
            try:
                environment_id = message.environment_id
                is_notes_visible = self.get_chatbot_instance(environment_id).toggle_notes()
                notes_message = "Notes are now visible." if is_notes_visible else "Notes are no longer visible"
                await message.send(notes_message)
            except Exception:
                self.logger.exception(f"Failed to toggle notes")
                await message.send("Failed to toggle notes.")

        async def reset_slash_command(message: AbstractMessage):
            if not await self.reflection_api.is_dm_or_admin(message):
                await message.send("You must be a guild admin or use this in DMs.")
                return

            environment_id = message.environment_id

            instance = ChatbotInstanceRegistry.get(environment_id, or_create=False)
            if instance:
                instance.cancel_all_schedules()
                instance.stop_news_background_task()
            ChatbotInstanceRegistry.remove(environment_id)
            self.logger.info(f"the conversation in {environment_id} has been reset, all scheduled tasks cancelled.")

            await message.send("Wha- Where am I?!")

        if self.platform == Platform.TELEGRAM:
            # for some reason event handlers in telegram are order dependent, meaning we should
            # run register_on_message_event after all slash commands are registered or else the
            # slash commands will not work.
            async def start_command(message: AbstractMessage):
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

    def get_chatbot_instance(self, identifier: str) -> AsyncChatbotInstance:
        instance = ChatbotInstanceRegistry.get(identifier,
            auth=self.auth,
            model=self.model,
            log_tool_calls=self.log_tool_calls
        )
        assert instance
        # Start news background task if feature is enabled and not already running
        if (
            PixiFeatures.NewsProactive in self.features
            and self.news_config is not None
            and instance.forum_id is not None
            and instance.news_task is None
        ):
            instance.start_news_background_task(
                news_config=self.news_config,
                reflection_api=self.reflection_api,
            )
        return instance

    async def pixi_resp(self, instance: AsyncChatbotInstance, reference_message: ChatMessageMeta):
        assert reference_message.origin
        message: AbstractMessage = reference_message.origin

        channel_id = message.environment.chat_id
        
        cancelled = False
        try:
            # concurrent_channel_stream_call handles overlapping requests automatically
            # killing tasks that are not done and restarting the request every time untill
            # one task finishes before the next request
            #
            # this way we can handle situations where the user is sending messages too quickly
            # with less tokens, but may increase response time, and killing tasks may result in
            # lost progress and http errors.
            #
            # TODO: find a solution to the above
            try:
                task = await instance.concurrent_channel_stream_call(
                    channel_id=str(channel_id),
                    reference_message=reference_message,
                )
                while not task.done():
                    try:
                        await message.typing()
                        await asyncio.sleep(3)
                    except ssl.SSLError:
                        self.logger.warning("SSLError occurred while sending typing status")
                    except Exception:
                        self.logger.exception("an error occurred while sending typing status")
                noncall_result = await task
                if noncall_result:
                    self.logger.warning(f"{noncall_result=}")
            except asyncio.CancelledError:
                cancelled = True
        except Exception:
            self.logger.exception(f"Unknown error while responding to a message in {instance.id}.")
            # await message.send(Messages.UNKNOWN_ERROR)

        return instance.action_manager.is_visible_actions_taken(), cancelled

    async def pixi_resp_retry(self, instance: AsyncChatbotInstance, chat_message: ChatMessageMeta, num_retry: int = 10):
        """
        create a copy of all messages in the conversation instance and try to respond to the message.
        if the response fails, it will retry up to `num_retry` times.
        if the response is successful, it will save the conversation instance and return True.
        if the response fails after all retries, it will return False.
        """

        instance.add_message(chat_message)
        messages_checkpoint = instance.get_messages().copy()
        for i in range(num_retry):
            try:
                responded, cancelled = await self.pixi_resp(instance, reference_message=chat_message)
                if not cancelled:
                    instance.save()
                if responded or cancelled:
                    return True
                else:
                    self.logger.warning("model didn't respond to a message. (invalid, requesting a response)")
                    # ask the model to respond again
                    instance.add_message("[SYSTEM]: You didn't respond, if this is intentional use the SEND action with no value.")
            except Exception:
                self.logger.exception(f"There was an error in `pixi_resp`, Retrying ({i}/{num_retry})")
                instance.set_messages(messages_checkpoint)

    def is_environment_allowed(self, identifier: str) -> bool:
        """
        Check if the environment identifier is allowed to be processed.
        """
        return self.environment_filter.is_allowed(identifier)

    async def should_respond(self, message: AbstractMessage) -> bool:
        # we should not process our own messages again
        if self.reflection_api.is_message_from_the_bot(message):
            return False
        
        environment_id = message.environment_id
        if not self.is_environment_allowed(environment_id):
            self.logger.warning(f"ignoring message in {environment_id} because it's not in an allowed environment.")
            return False
        
        if self.reflection_api.is_bot_mentioned(message) or message.is_inside_dm():
            return True

        message_text = message.content
        if message_text is None:
            message_text = ""

        # check if the message contains a summon word or a prefixed command
        is_keyword_present = False
        for keyword in SUMMON_KEYWORDS:
            if keyword in message_text.lower():
                is_keyword_present = True
                break
        is_prefixed = message_text.lower().startswith(tuple(["!" + k for k in SUMMON_KEYWORDS]))

        return is_prefixed or is_keyword_present
    
    async def __add_reply_metadata(self, instance: AsyncChatbotInstance, metadata: dict, message: AbstractMessage):
        # process reply reference
        reply_message = await message.fetch_reference()
        if reply_message is not None and reply_message.content is not None:
            reply_message_text = remove_prefixes(reply_message.content)
            # if the reply is to the last message in the instance, we don't need to do anything.
            reply_optimization = -1
            instance_messages = instance.get_messages()
            matching_messages = [
                msg.content for msg in instance_messages if msg.content is not None and reply_message_text in msg.content
            ]
            if matching_messages:
                if instance_messages[-1].content in matching_messages:
                    reply_optimization = 2
                else:
                    reply_optimization = 1
            if reply_optimization == 2:
                # completely ignore reply context
                self.logger.debug(f"completely ignore reply context for {message.environment_id=}")
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
    
    async def on_message(self, message: AbstractMessage):
        if not await self.should_respond(message):
            return

        message_text = message.content
        if message_text is None:
            message_text = ""

        message_text = remove_prefixes(message_text)
        environment_id = message.environment_id

        instance = self.get_chatbot_instance(environment_id)

        metadata = dict(
            from_user=asdict(message.author)
        )
        await self.__add_reply_metadata(instance, metadata, message)
                    
        def rearrage_predicate(msg: ChatMessageMeta):
            msg_channel_id = msg.origin.environment.chat_id if msg.origin else None
            current_channel_id = chat_message.origin.environment.chat_id if chat_message.origin else None

            if msg_channel_id is None or current_channel_id is None:
                return False
            return msg_channel_id == current_channel_id
        
        instance.update_realtime(self.reflection_api.get_realtime_data(message))
        instance.set_rearrange_predicate(rearrage_predicate)

        # convert everything into `ChatMessageMeta`
        chat_message = ChatMessageMeta(
            role=ChatRole.USER,
            content=message_text,
            metadata=metadata,
            images=await message.fetch_images() if self.accept_images else [],
            audio=await message.fetch_audio() if self.accept_audio else [],
            # the following properties are intended to be used internally and are NOT reload persistant
            instance_id=environment_id,
            # origin is used for actions and tool calls
            origin=message
        )

        await self.pixi_resp_retry(instance, chat_message)

    def register_pre_startup_hook(self, hook: Callable[..., Coroutine[Any, Any, Any]]):
        """Register an async awaitable to run before the bot connects to Discord/Telegram.

        The hook will be awaited concurrently before the platform connection starts.
        This allows running async initialization code (e.g., database migrations,
        cache warming, API pre-checks) before the bot begins handling messages.
        """
        self.pre_startup_hooks.append(hook)

    def register_post_startup_hook(self, hook: Callable[..., Coroutine[Any, Any, Any]]):
        """Register an async awaitable to run after the bot connects to Discord/Telegram.

        The hook will be awaited concurrently after the platform connection starts.
        This allows running async initialization code (e.g., database migrations,
        cache warming, API pre-checks) after the bot begins handling messages.
        """
        self.post_startup_hooks.append(hook)

    async def __post_startup_task(self):
        await self.reflection_api.wait_until_ready()
        if self.post_startup_hooks:
            self.logger.info(f"Running {len(self.post_startup_hooks)} post-startup hook(s)...")
            await asyncio.gather(*(f() for f in self.post_startup_hooks))
            self.logger.info("All post-startup hooks completed.")

    async def start(self):
        """Start the bot asynchronously, running all startup hooks first."""
        if self.pre_startup_hooks:
            self.logger.info(f"Running {len(self.pre_startup_hooks)} pre-startup hook(s)...")
            await asyncio.gather(*(f() for f in self.pre_startup_hooks))
            self.logger.info("All pre-startup hooks completed.")

        post_task = asyncio.create_task(self.__post_startup_task())

        await self.reflection_api.start_async()
        await post_task

    def run(self):
        """Run the bot (blocking with async support for startup hooks)."""
        asyncio.run(self.start())
