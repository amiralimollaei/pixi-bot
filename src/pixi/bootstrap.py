"""Construct production adapters and connect them to the bot application."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from pixi.caching import MediaCacheProvider
from pixi.caching.disk import CacheDiskStorage
from pixi.interfaces.caching import CacheStorage
from pixi.interfaces.knowledge import KnowledgeStorage
from pixi.interfaces.messages import MessagesStorage
from pixi.interfaces.platform import PlatformMessage, PlatformProvider
from pixi.model.config import (
    IdFilter,
    KnowledgeBaseConfig,
    LlamaEmbeddingModelConfig,
    LlamaLanguageModelConfig,
    MediaWikiConfig,
    OpenAIAuthConfig,
    OpenAIEmbeddingModelConfig,
    OpenAILanguageModelConfig,
    PixiFeatures,
)
from pixi.model.enums import Platform
from pixi.storage.paths import PixiPaths, copy_default_resources

if TYPE_CHECKING:
    from pixi.bot.client import PixiClient


def create_platform_provider(
    platform: Platform,
    *,
    media_cache: MediaCacheProvider | None = None,
) -> PlatformProvider:
    """Import only the selected platform SDK."""
    try:
        match platform:
            case Platform.DISCORD:
                from pixi.platform.discord import DiscordProvider

                return DiscordProvider(media_cache=media_cache)
            case Platform.TELEGRAM:
                from pixi.platform.telegram import TelegramProvider

                return TelegramProvider(media_cache=media_cache)
            case _:
                raise RuntimeError(f"PlatformProvider unknown platform {platform}.")
    except ImportError as error:
        raise RuntimeError(
            f"PlatformProvider for {platform} is not available; install its optional dependencies."
        ) from error


async def verify_models(auth: OpenAIAuthConfig, models: dict[str, str]) -> None:
    """Verify the configured OpenAI-compatible backend before platform startup."""
    from pixi.apis.openai.client import OpenAI
    from pixi.apis.openai.exceptions import (
        APIConnectionError,
        APIError,
        AuthenticationError,
    )

    logger = logging.getLogger(__name__)
    logger.info(
        "Verifying API connectivity and model availability at %s...", auth.base_url
    )
    try:
        session = OpenAI(api_key=auth.api_key, base_url=auth.base_url)
        available_models = {model.id for model in session.models.list()}
        if not available_models:
            raise RuntimeError("No model available on the API server.")
        logger.info("Found %s model(s) available:", len(available_models))
        for model_id in available_models:
            logger.info(" - %s", model_id)
        for role, model_id in models.items():
            if model_id not in available_models:
                raise RuntimeError(
                    f'{role} model "{model_id}" was not found in the list of available models on the API server.'
                )
    except APIConnectionError as error:
        raise RuntimeError(
            f"Failed to connect to API at {auth.base_url}: {error}"
        ) from error
    except AuthenticationError as error:
        raise RuntimeError(
            f"Failed to authenticate to API at {auth.base_url}: {error}"
        ) from error
    except APIError as error:
        logger.warning(
            "API responded with an error when listing models (status=%s), model verification "
            "will be skipped. This is expected for some OpenAI-compatible backends.",
            error.code,
        )


def create_bot(
    platform: Platform,
    *,
    auth: OpenAIAuthConfig,
    model: OpenAILanguageModelConfig | LlamaLanguageModelConfig,
    helper_model: OpenAILanguageModelConfig | LlamaLanguageModelConfig | None = None,
    embedding_model: OpenAIEmbeddingModelConfig
    | LlamaEmbeddingModelConfig
    | None = None,
    features: PixiFeatures = PixiFeatures.default(),
    knowledge_bases: Sequence[KnowledgeBaseConfig] = (),
    wikis: Sequence[MediaWikiConfig] = (),
    environment_filter: IdFilter | None = None,
    instance_idle_timeout: float = 900.0,
    directory: str | Path = PixiPaths.DEFAULT_ROOT,
    messages_storage: MessagesStorage | None = None,
    cache_storage: CacheStorage | None = None,
    knowledge_storage: KnowledgeStorage | None = None,
) -> PixiClient:
    """Build the bot; callers own the lifecycle of injected storage backends."""
    PixiPaths.set_root(directory)
    copy_default_resources()

    # Path-sensitive adapters are imported only after configuring their data root.
    from pixi.addon import AddonManager
    from pixi.ai.chatting.persona import AssistantPersona
    from pixi.ai.rag.client import AsyncRAGClient
    from pixi.apis.openai.adapter import OpenAIChatModel, OpenAIEmbeddingModel
    from pixi.bot.actions import (
        CancelScheduleAction,
        NoteAction,
        ReactAction,
        ScheduleAction,
        SendAction,
        SendGifAction,
    )
    from pixi.bot.client import PixiClient
    from pixi.bot.tools import (
        FetchChannelHistoryTool,
        create_knowledge_tools,
        create_mediawiki_tools,
    )
    from pixi.caching import get_embedding_cache, get_media_cache
    from pixi.inference.chat import LlamaChatModel
    from pixi.storage.messages import MessagesDiskStorage

    logger = logging.getLogger(__name__)
    if cache_storage is None:
        cache_storage = CacheDiskStorage(PixiPaths.cache())
    media_cache = None
    if PixiFeatures.ImageSupport in features or PixiFeatures.AudioSupport in features:
        try:
            media_cache = get_media_cache(storage=cache_storage)
        except RuntimeError as error:
            logger.warning("%s Disabling image/audio support.", error)
            features &= ~(PixiFeatures.ImageSupport | PixiFeatures.AudioSupport)

    with PixiPaths.persona().open(encoding="utf-8") as resource:
        persona = AssistantPersona.from_dict(json.load(resource))
    with PixiPaths.system_prompt().open(encoding="utf-8") as resource:
        system_prompt_template = resource.read()
    with PixiPaths.examples().open(encoding="utf-8") as resource:
        examples = resource.read()

    platform_provider = create_platform_provider(platform, media_cache=media_cache)
    helper_model = helper_model or model
    native_models = []
    if isinstance(model, LlamaLanguageModelConfig):
        chat_model = LlamaChatModel(model, media_cache=media_cache)
        native_models.append(chat_model)
    else:
        chat_model = OpenAIChatModel(auth, model, media_cache=media_cache)
    if helper_model is model:
        helper_chat_model = chat_model
    elif isinstance(helper_model, LlamaLanguageModelConfig):
        helper_chat_model = LlamaChatModel(helper_model, media_cache=media_cache)
        native_models.append(helper_chat_model)
    else:
        helper_chat_model = OpenAIChatModel(auth, helper_model, media_cache=media_cache)
    rag_factory = None
    close_embeddings = None
    if embedding_model is not None:
        if isinstance(embedding_model, LlamaEmbeddingModelConfig):
            from pixi.inference.embeddings import LlamaEmbeddingModel

            embedding_provider = LlamaEmbeddingModel(embedding_model)
            close_embeddings = embedding_provider.aclose
        else:
            embedding_provider = OpenAIEmbeddingModel(auth, embedding_model)
        embedding_cache = get_embedding_cache(
            storage=cache_storage,
            embedding_model=embedding_provider,
        )

        def create_rag_client():
            return AsyncRAGClient(cache=embedding_cache, model=embedding_model)

        rag_factory = create_rag_client

    bot = PixiClient(
        platform_provider,
        chat_model=chat_model,
        model=model,
        helper_chat_model=helper_chat_model,
        helper_model=helper_model,
        embedding_model=embedding_model,
        rag_factory=rag_factory,
        messages_storage=(
            messages_storage
            if messages_storage is not None
            else MessagesDiskStorage(PixiPaths.messages())
        ),
        persona=persona,
        system_prompt_template=system_prompt_template,
        examples=examples,
        features=features,
        environment_filter=environment_filter,
        instance_idle_timeout=instance_idle_timeout,
    )

    if close_embeddings is not None:
        bot.register_shutdown_hook(close_embeddings)

    for native_model in native_models:
        bot.register_shutdown_hook(native_model.aclose)

    model_ids = {}
    if isinstance(model, OpenAILanguageModelConfig):
        model_ids["main"] = model.id
    if isinstance(helper_model, OpenAILanguageModelConfig):
        model_ids["helper"] = helper_model.id
    if isinstance(embedding_model, OpenAIEmbeddingModelConfig):
        model_ids["embedding"] = embedding_model.id
    if model_ids:
        bot.register_pre_startup_hook(lambda: verify_models(auth, model_ids))

    gif_api = None
    if PixiFeatures.GIFSearch in features:
        from pixi.apis.tenor import AsyncTenorAPI

        try:
            gif_api = AsyncTenorAPI()
        except Exception:
            logger.warning(
                "gif search api failed to initialize, gif features will not be available."
            )
    for action in (
        ScheduleAction(),
        CancelScheduleAction(),
        SendAction(),
        SendGifAction(gif_api),
        NoteAction(),
        ReactAction(),
    ):
        bot.register_action(action)

    if PixiFeatures.ToolCalling in features:
        from pixi.storage.knowledge import KnowledgeBase
        from pixi.storage.knowledge_disk import KnowledgeDiskStorage

        if knowledge_storage is None:
            knowledge_storage = KnowledgeDiskStorage(PixiPaths.knowledge())

        for config in knowledge_bases:
            knowledge_base = KnowledgeBase.from_storage(config.name, knowledge_storage)
            bot.knowledge_bases.append(knowledge_base)
            for tool in create_knowledge_tools(bot, config.name, knowledge_base):
                bot.register_tool(tool)
        if PixiFeatures.WikiSearch in features:
            from pixi.apis.wikimedia import AsyncWikimediaAPI

            for config in wikis:
                for tool in create_mediawiki_tools(
                    bot, config.name, AsyncWikimediaAPI(config.url)
                ):
                    bot.register_tool(tool)
        if platform == Platform.DISCORD:
            bot.register_tool(FetchChannelHistoryTool())

    if platform == Platform.TELEGRAM:

        async def start_command(message: PlatformMessage):
            await message.send("Hiiiii, how's it going?")

        bot.register_slash_command("start", start_command)

    addon_manager = AddonManager(bot)
    addon_manager.load_addons()
    return bot
