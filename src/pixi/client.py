import asyncio
import logging
import math
from dataclasses import asdict
from typing import Any, Callable, Coroutine, Optional

from .actions import (CancelScheduleAction, NoteAction, ReactAction,
                      ScheduleAction, SendAction, SendGifAction)
from .addon import AddonManager
from .agents import AgentBase
from .caching import get_caching_provider
from .chatting import AsyncChatbotInstance, ChatbotInstanceRegistry
from .model.chatting.callbacks import AsyncAction, AsyncTool
from .model.config import (DatasetConfig, IdFilter, MediaWikiConfig,
                           NewsConfig, OpenAIAuthConfig,
                           OpenAIEmbeddingModelConfig,
                           OpenAILanguageModelConfig, PixiFeatures)
from .model.enums import ChatRole, Platform
from .model.storage.message import ChatMessageMeta
from .platform import PlatformMessage, PlatformProvider, get_platform_provider
from .tools import (FetchChannelHistoryTool, create_database_tools,
                    create_mediawiki_tools)

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
        instance_idle_timeout: float = 900.0,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Initalizing Pixi with feature set {features} and platform {platform}...")
        if not math.isfinite(instance_idle_timeout) or instance_idle_timeout <= 0:
            raise ValueError("instance_idle_timeout must be a positive finite number of seconds.")

        self.auth = auth
        self.model = model
        self.helper_model = helper_model or model
        self.embedding_model = embedding_model
        self.features = features
        self.news_config = news_config
        self.instance_idle_timeout = instance_idle_timeout
        self.pre_startup_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []
        self.post_startup_hooks: list[Callable[..., Coroutine[Any, Any, Any]]] = []

        # Verify models and API connectivity at startup
        self.register_pre_startup_hook(self.verify_models)

        # Proactive news needs its guild instances even before the first message.
        if PixiFeatures.NewsProactive in self.features and news_config is not None:
            self.register_post_startup_hook(self._start_news_instances)

        self.datasets = []
        self.environment_filter = environment_filter

        if PixiFeatures.ImageSupport in self.features or PixiFeatures.AudioSupport in self.features:
            try:
                get_caching_provider()
            except RuntimeError as error:
                self.logger.warning("%s Disabling image/audio support.", error)
                self.features &= ~(PixiFeatures.ImageSupport | PixiFeatures.AudioSupport)

        ChatbotInstanceRegistry.init(hash_prefix=platform, bot=self)

        self.platform_provider: PlatformProvider = get_platform_provider(platform)()

        if PixiFeatures.GIFSearch in self.features:
            try:
                from .apis.tenor import AsyncTenorAPI
                SendGifAction.gif_api = AsyncTenorAPI()
            except Exception:
                self.logger.warning("gif search api failed to initialize, gif features will not be available.")

        self.__register_builtin_actions()

        if PixiFeatures.ToolCalling in self.features and datasets:
            self.logger.info(f"registering {len(datasets)} dataset(s):")
            for dataset_config in datasets:
                self.logger.info(f" - {dataset_config.name}")
                self.datasets.append(self.register_database_tool(dataset_config))

        if PixiFeatures.ToolCalling in self.features and PixiFeatures.WikiSearch in features and wikis:
            self.logger.info(f"registering {len(wikis)} wiki(s):")
            for wiki_config in wikis:
                self.logger.info(f" - {wiki_config.name}: {wiki_config.url}")
                self.register_mediawiki_tools(url=wiki_config.url, wiki_name=wiki_config.name)

        if platform == Platform.DISCORD and PixiFeatures.ToolCalling in self.features:
            self.__register_discord_specific_tools()

        self.__register_builtin_slash_commands()
        
        if platform == Platform.TELEGRAM:
            self.__register_telegram_specific_slash_commands()

        self.logger.info(f"loading addons...")
        self.addon_manager = AddonManager(self)
        self.addon_manager.load_addons()

        self.platform_provider.register_on_message_event(self.on_message)

        self.logger.info(f"Pixi finished initalizing!")

    def __register_telegram_specific_slash_commands(self):
        async def start_command(message: PlatformMessage):
            await message.send("Hiiiii, how's it going?")

        self.register_slash_command(name="start", function=start_command)

    async def _start_news_instances(self):
        self.logger.info("Starting proactive news for available guilds...")
        for guild in await self.platform_provider.get_available_guilds():
            instance_id = f"forum#{guild.id}"
            self.logger.info(f" - \"{guild.name}\" (members: {guild.member_count})")
            self.get_chatbot_instance(instance_id)

    async def _evict_idle_instances(self):
        while True:
            await asyncio.sleep(min(60.0, self.instance_idle_timeout))
            ChatbotInstanceRegistry.evict_idle(self.instance_idle_timeout)

    async def verify_models(self):
        """
        Verifies that the configured models exist on the API server and that the API is reachable.
        Logs a warning for any configured model IDs not found in the API's model list.
        Raises RuntimeError if the API is unreachable.
        """
        from . import openai

        self.logger.info(f"Verifying API connectivity and model availability at {self.auth.base_url}...")

        try:
            session = openai.OpenAI(
                api_key=self.auth.api_key,
                base_url=self.auth.base_url,
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

    def register_tool(self, tool: AsyncTool):
        if PixiFeatures.ToolCalling not in self.features:
            self.logger.warning("tried to register a tool, but tool calls are disabled, ignoring...")
            return

        ChatbotInstanceRegistry.register_tool(tool)

    def register_action(self, action: AsyncAction):
        ChatbotInstanceRegistry.register_action(action)

    def create_agent_instance[A: AgentBase](self, agent_cls: type[A], **agent_kwargs) -> A:
        return agent_cls(auth=self.auth, model=self.helper_model, log_tool_calls=PixiFeatures.ToolLogging in self.features, **agent_kwargs)

    def register_slash_command(self, name: str, function, description: str | None = None):
        async def checked_function(message: PlatformMessage):
            environment_id = message.environment_id
            if not self.is_environment_allowed(environment_id):
                self.logger.warning(
                    f"ignoring slash command in {environment_id} because it is not in the allowed places.")
                await message.send("This command is not allowed here.")
                return
            await function(message)
        self.platform_provider.register_slash_command(name, checked_function, description)

    async def typing_delay(self, message: PlatformMessage, delay: float):
        delay_served = 0.0
        while delay_served < delay:
            await message.typing()
            await asyncio.sleep(3.0)
            delay_served += 3.0

    def __register_builtin_actions(self):
        self.register_action(ScheduleAction())
        self.register_action(CancelScheduleAction())
        self.register_action(SendAction())
        self.register_action(SendGifAction())
        self.register_action(NoteAction())
        self.register_action(ReactAction())

    def register_database_tool(self, dataset_config: DatasetConfig):
        from .storage.database import DirectoryDatabase

        if PixiFeatures.ToolCalling not in self.features:
            self.logger.warning("tried to initalize a database tool, but tool calls are disabled")
            return

        database_name = dataset_config.name
        database_api = DirectoryDatabase.from_directory(dataset_config.name)

        for tool in create_database_tools(self, database_name, database_api):
            self.register_tool(tool)
        return database_api

    def register_mediawiki_tools(self, url: str, wiki_name: str):
        if PixiFeatures.ToolCalling not in self.features:
            self.logger.warning("tried to initalize a mediawiki tool, but tool calls are disabled")
            return

        from .apis.wikimedia import AsyncWikimediaAPI

        wiki_api = AsyncWikimediaAPI(url)

        for tool in create_mediawiki_tools(self, wiki_name, wiki_api):
            self.register_tool(tool)

    def __register_discord_specific_tools(self):
        if PixiFeatures.ToolCalling not in self.features:
            self.logger.warning("tried to initalize discord specific tools, but tool calls are disabled")
            return

        self.register_tool(FetchChannelHistoryTool())

    def __register_builtin_slash_commands(self):
        async def notes_slash_command(message: PlatformMessage):
            if not await self.platform_provider.is_dm_or_admin(message):
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

        async def reset_slash_command(message: PlatformMessage):
            if not await self.platform_provider.is_dm_or_admin(message):
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
        instance = ChatbotInstanceRegistry.get(
            identifier,
            auth=self.auth,
            model=self.model,
            log_tool_calls=PixiFeatures.ToolLogging in self.features
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
                reflection_api=self.platform_provider,
            )
        return instance

    async def pixi_resp(self, instance: AsyncChatbotInstance, reference_message: ChatMessageMeta):
        assert reference_message.origin
        message: PlatformMessage = reference_message.origin

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
                    except OSError:
                        self.logger.warning("OSError occurred while sending typing status")
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
                    instance.add_message(
                        "[SYSTEM]: You didn't respond, if this is intentional use the SEND action with no value.")
            except Exception:
                self.logger.exception(f"There was an error in `pixi_resp`, Retrying ({i}/{num_retry})")
                instance.set_messages(messages_checkpoint)

    def is_environment_allowed(self, identifier: str) -> bool:
        """
        Check if the environment identifier is allowed to be processed.
        """
        return self.environment_filter.is_allowed(identifier)

    async def should_respond(self, message: PlatformMessage) -> bool:
        # we should not process our own messages again
        if self.platform_provider.is_message_from_the_bot(message):
            return False

        environment_id = message.environment_id
        if not self.is_environment_allowed(environment_id):
            self.logger.warning(f"ignoring message in {environment_id} because it's not in an allowed environment.")
            return False

        if self.platform_provider.is_bot_mentioned(message) or message.is_inside_dm():
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

    async def __add_reply_metadata(self, instance: AsyncChatbotInstance, metadata: dict, message: PlatformMessage):
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
            elif reply_message and self.platform_provider.is_message_from_the_bot(reply_message):
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

    async def on_message(self, message: PlatformMessage):
        if not await self.should_respond(message):
            return

        message_text = message.content
        if message_text is None:
            message_text = ""

        message_text = remove_prefixes(message_text)
        environment_id = message.environment_id

        instance = self.get_chatbot_instance(environment_id)

        with instance.use():
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

            instance.update_realtime(self.platform_provider.get_realtime_data(message))
            instance.set_rearrange_predicate(rearrage_predicate)

            # convert everything into `ChatMessageMeta`
            chat_message = ChatMessageMeta(
                role=ChatRole.USER,
                content=message_text,
                metadata=metadata,
                image_hashes=await message.fetch_images() if PixiFeatures.ImageSupport in self.features else [],
                audio_hashes=await message.fetch_audio() if PixiFeatures.AudioSupport in self.features else [],
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
        await self.platform_provider.wait_until_ready()
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
        eviction_task = asyncio.create_task(self._evict_idle_instances(), name="idle-instance-eviction")

        try:
            await self.platform_provider.start_async()
            await post_task
        except asyncio.CancelledError:
            pass
        finally:
            post_task.cancel()
            eviction_task.cancel()
            await asyncio.gather(post_task, eviction_task, return_exceptions=True)
            await self.platform_provider.close_async()

    def run(self):
        """Run the bot (blocking with async support for startup hooks)."""
        asyncio.run(self.start())
