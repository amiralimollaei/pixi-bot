import logging
from contextlib import ExitStack


def load_dotenv():
    """Load optional environment-file settings at the executable boundary."""
    try:
        import dotenv
    except ImportError:
        logging.warning("dotenv is not installed, install it using `pip install dotenv`")
    else:
        dotenv.load_dotenv()


def main():
    import argparse
    import logging
    import math
    import os


    from .model.enums.ansi import AnsiColors
    
    from .model.enums import Platform
    from .model.config import (DatasetConfig, IdFilter, LlamaEmbeddingModelConfig,
                               LlamaLanguageModelConfig, MediaWikiConfig, NewsConfig,
                               OpenAIAuthConfig, OpenAIEmbeddingModelConfig,
                               OpenAILanguageModelConfig, PixiFeatures)

    # injecting colors into the default logger

    COLORS = {  # (level_color, message_color)
        logging.DEBUG: (AnsiColors.BLUE, AnsiColors.BEIGE),
        logging.INFO: (AnsiColors.WHITE, AnsiColors.WHITE2),
        logging.WARNING: (AnsiColors.YELLOW, AnsiColors.YELLOW2),
        logging.ERROR: (AnsiColors.RED, AnsiColors.RED2),
        logging.CRITICAL: (AnsiColors.BOLD + AnsiColors.RED, AnsiColors.BOLD + AnsiColors.RED2)
    }

    orig_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = orig_factory(*args, **kwargs)
        level_color, message_color = COLORS.get(record.levelno, (AnsiColors.GREY, AnsiColors.WHITE))
        record.level_color = level_color
        record.message_color = message_color
        return record
    logging.setLogRecordFactory(record_factory)

    logging.basicConfig(
        format=f"{AnsiColors.GREY}[{AnsiColors.BLUE}%(asctime)s{AnsiColors.GREY}] {AnsiColors.GREY}[%(level_color)s%(levelname)s / %(name)s{AnsiColors.GREY}] %(message_color)s%(message)s{AnsiColors.END}",
        level=logging.INFO,
        force=True,
    )

    # https://github.com/langchain-ai/langchain/issues/14065#issuecomment-1834571761
    # Get the logger for 'httpx'
    httpx_logger = logging.getLogger("httpx")
    # Set the logging level to WARNING to ignore INFO and DEBUG logs
    httpx_logger.setLevel(logging.WARNING)

    # load environment variables
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the Pixi bot, a multi-platform AI chatbot.")
    parser.add_argument(
        "--platform", "-p",
        type=str,
        choices=[p.name.lower() for p in Platform],
        required=True,
        help="Platform to run the bot on."
    )
    parser.add_argument(
        "--pixi-directory", "-pd",
        type=str,
        default="~/.pixi/",
        help="The root directory for configuration files, addons, userdata, assets and cache, defaults to \"~/.pixi/\""
    )
    parser.add_argument(
        "--log-level", "-l",
        type=str,
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Set the logging level."
    )
    parser.add_argument(
        "--instance-idle-timeout",
        type=float,
        default=900.0,
        help="Unload inactive conversation runtime state after this many seconds (default: 900); history stays in storage."
    )
    parser.add_argument(
        "--messages-storage",
        choices=("disk", "sql", "redis"),
        default="disk",
        help="Message-history backend (default: disk under userdata/messages).",
    )
    parser.add_argument(
        "--messages-storage-url",
        metavar="URL",
        help="SQLAlchemy or Redis URL; defaults to DATABASE_URL for sql, REDIS_URL for redis.",
    )
    parser.add_argument(
        "--redis-key-prefix",
        metavar="PREFIX",
        help="Redis history key namespace (default: pixi:messages:); requires redis storage.",
    )
    parser.add_argument(
        "--cache-storage",
        choices=("disk", "sql", "redis"),
        default="disk",
        help="Media/embedding cache backend (default: disk under the cache directory).",
    )
    parser.add_argument(
        "--cache-storage-url",
        metavar="URL",
        help="Cache SQLAlchemy or Redis URL; defaults to DATABASE_URL for sql, REDIS_URL for redis.",
    )
    parser.add_argument(
        "--cache-redis-key-prefix",
        metavar="PREFIX",
        help="Redis cache namespace (default: pixi:cache:); requires --cache-storage redis.",
    )
    parser.add_argument(
        "--api-url", "-a",
        type=str,
        default="https://api.openai.com/v1",
        help="OpenAI Compatible API URL to use for the bot"
    )
    parser.add_argument(
        "--auth",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="whether or not to authorize to the API backends"
    )

    # model arguments
    model_selection = parser.add_mutually_exclusive_group(required=True)
    model_selection.add_argument(
        "--model", "-m",
        type=str,
        help="OpenAI-compatible language model to use for the main chatbot",
    )
    model_selection.add_argument(
        "--llama-hf",
        metavar="REPO[:QUANT]",
        help="Use a local llama.cpp model downloaded from Hugging Face",
    )
    parser.add_argument("--llama-file", metavar="FILE",
                        help="Optional GGUF filename; requires --llama-hf")
    parser.add_argument("--llama-binary", metavar="PATH",
                        help="Path to llama-server; requires --llama-hf")
    parser.add_argument("--llama-idle-timeout", type=float, metavar="SECONDS",
                        help="Stop the local chat server after this idle period; requires --llama-hf")
    parser.add_argument(
        "--model-max-context", "-ctx", type=int, default=16192,
        help="Maximum model context size (default: 16192).",
    )
    parser.add_argument(
        "--helper-model-max-context", "-hctx", type=int, default=16192,
        help="Maximum helper model context size (default: 16192).",
    )
    helper_selection = parser.add_mutually_exclusive_group()
    helper_selection.add_argument(
        "--helper-model", "-hm",
        type=str,
        help="OpenAI-compatible language model to use for agentic tools",
    )
    helper_selection.add_argument(
        "--llama-helper-hf",
        metavar="REPO[:QUANT]",
        help="Use a local llama.cpp model for agentic tools",
    )
    parser.add_argument("--llama-helper-file", metavar="FILE",
                        help="Optional helper GGUF filename; requires --llama-helper-hf")
    parser.add_argument("--llama-helper-binary", metavar="PATH",
                        help="Path to helper llama-server; requires --llama-helper-hf")
    parser.add_argument("--llama-helper-idle-timeout", type=float, metavar="SECONDS",
                        help="Stop the local helper server after this idle period; requires --llama-helper-hf")

    # Embedding inference is explicitly either API-backed or local.
    embedding_selection = parser.add_mutually_exclusive_group()
    embedding_selection.add_argument(
        "--embedding-model", "-em",
        type=str,
        help="OpenAI-compatible API model to use for embedding tools",
    )
    embedding_selection.add_argument(
        "--llama-embedding-hf",
        metavar="REPO[:QUANT]",
        help="Opt into local embeddings using llama-server and its native Hugging Face downloads",
    )
    parser.add_argument(
        "--llama-embedding-file",
        metavar="FILE",
        help="Optional GGUF filename in the selected Hugging Face repository",
    )
    parser.add_argument(
        "--llama-embedding-binary",
        metavar="PATH",
        help="Path to llama-server (default: llama-server on PATH); requires --llama-embedding-hf",
    )
    parser.add_argument(
        "--llama-embedding-idle-timeout",
        type=float,
        metavar="SECONDS",
        help="Stop the local embedding server after this idle period (default: 60)",
    )
    parser.add_argument(
        "--embedding-model-max-context", "-ectx",
        type=int,
        default=None,
        help="Embedding context tokens (default: 16192 for API; model's native context for llama.cpp)",
    )
    parser.add_argument(
        "--embedding-model-dimension", "-ed",
        type=int,
        default=None,
        help="API embedding dimension (default: 768); local GGUF models use their native dimension",
    )
    parser.add_argument(
        "--embedding-model-min-size", "-emin",
        type=int,
        default=256,
        help="Minimum chunk size to use for embedding tools, Default is '256`.",
    )
    parser.add_argument(
        "--embedding-model-max-size", "-emax",
        type=int,
        default=1024,
        help="Maximum chunk size to use for embedding tools, Default is '1024`.",
    )

    # feature arguments
    default_features = PixiFeatures.default()

    parser.add_argument(
        "--tool-calling",
        action=argparse.BooleanOptionalAction,
        default=PixiFeatures.ToolCalling in default_features,
        help="allows pixi to use built-in and/or plugin tools, tool calling can only be used if the model supports them"
    )
    parser.add_argument(
        "--tool-logging",
        action=argparse.BooleanOptionalAction,
        default=PixiFeatures.ToolLogging in default_features,
        help="verbose logging for tool calls (enabled by default when running with logging level DEBUG)"
    )
    parser.add_argument(
        "--wiki-search",
        action=argparse.BooleanOptionalAction,
        default=PixiFeatures.WikiSearch in default_features,
        help="allows pixi to search any mediawiki compatible Wiki"
    )
    parser.add_argument(
        "--gif-search",
        action=argparse.BooleanOptionalAction,
        default=PixiFeatures.GIFSearch in default_features,
        help="allows pixi to search for gifs online, and send them in chat"
    )
    parser.add_argument(
        "--image-support",
        action=argparse.BooleanOptionalAction,
        default=PixiFeatures.ImageSupport in default_features,
        help="allows pixi to download and process image files"
    )
    parser.add_argument(
        "--audio-support",
        action=argparse.BooleanOptionalAction,
        default=PixiFeatures.AudioSupport in default_features,
        help="allows pixi to download and process audio files"
    )

    # proactive news arguments
    parser.add_argument(
        "--news-feed-url", "-n",
        type=str,
        default=None,
        help="RSS/Atom feed URL for proactive news feature. Enables the news feature if provided."
    )
    parser.add_argument(
        "--news-interval",
        type=int,
        default=3600,
        help="Seconds between news checks for proactive news feature. Default is 3600 (1 hour)."
    )
    parser.add_argument(
        "--news-probability",
        type=float,
        default=0.1,
        help="Probability of sending a proactive news message each check (0.0 to 1.0). Default is 0.1."
    )

    # environment filter arguments
    parser.add_argument(
        "--environment-whitelist",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="whether or not the ids passed to environment ids are whitelisted or blacklisted"
    )
    parser.add_argument(
        "--environment-ids",
        type=str,
        nargs="+",
        default=None,
        help="add the id of the environment that the bot is or is not allowed to respond in (space-separated). If not provided, the bot will respond everywhere."
    )

    # database arguments
    parser.add_argument(
        "--database-names", "-db",
        type=str,
        nargs="+",
        default=[],
        help="add the name of databases to use (space-separated)."
    )

    # mediawiki wiki arguments
    parser.add_argument(
        "--mediawiki-wikis", "-mw",
        type=str,
        nargs="+",
        default=[],
        help="add the mediawiki wikis to use (space-separated), it should follow the format of `name=url`, Example: wikipedia=https://www.wikipedia.org/w/"
    )

    args = parser.parse_args()
    if args.messages_storage == "sql" and args.messages_storage_url is None:
        args.messages_storage_url = os.getenv("DATABASE_URL")
    elif args.messages_storage == "redis" and args.messages_storage_url is None:
        args.messages_storage_url = os.getenv("REDIS_URL")
    if args.messages_storage == "disk":
        if args.messages_storage_url is not None:
            parser.error("--messages-storage-url requires --messages-storage sql or redis.")
    elif not args.messages_storage_url:
        parser.error("SQL/Redis storage requires --messages-storage-url or DATABASE_URL/REDIS_URL.")
    if args.redis_key_prefix is not None and args.messages_storage != "redis":
        parser.error("--redis-key-prefix requires --messages-storage redis.")
    if args.cache_storage == "sql" and args.cache_storage_url is None:
        args.cache_storage_url = os.getenv("DATABASE_URL")
    elif args.cache_storage == "redis" and args.cache_storage_url is None:
        args.cache_storage_url = os.getenv("REDIS_URL")
    if args.cache_storage == "disk":
        if args.cache_storage_url is not None:
            parser.error("--cache-storage-url requires --cache-storage sql or redis.")
    elif not args.cache_storage_url:
        parser.error("SQL/Redis caching requires --cache-storage-url or DATABASE_URL/REDIS_URL.")
    if args.cache_redis_key_prefix is not None and args.cache_storage != "redis":
        parser.error("--cache-redis-key-prefix requires --cache-storage redis.")

    local_options = (
        (args.llama_hf, (args.llama_file, args.llama_binary, args.llama_idle_timeout),
         "--llama-hf"),
        (args.llama_helper_hf, (args.llama_helper_file, args.llama_helper_binary,
                                args.llama_helper_idle_timeout), "--llama-helper-hf"),
    )
    for selected_repo, options, selector in local_options:
        if not selected_repo and any(value is not None for value in options):
            parser.error(f"Local model options require {selector}.")
    if args.model_max_context <= 0 or args.helper_model_max_context <= 0:
        parser.error("Model context limits must be positive.")

    for timeout, option in (
        (args.llama_idle_timeout, "--llama-idle-timeout"),
        (args.llama_helper_idle_timeout, "--llama-helper-idle-timeout"),
    ):
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            parser.error(f"{option} must be a positive finite number.")
    local_options = (
        args.llama_embedding_file,
        args.llama_embedding_binary,
        args.llama_embedding_idle_timeout,
    )
    if not args.llama_embedding_hf and any(value is not None for value in local_options):
        parser.error("Local embedding options require --llama-embedding-hf.")
    if args.llama_embedding_hf:
        if args.embedding_model_dimension is not None:
            parser.error("--embedding-model-dimension is API-only; local models use their native dimension.")
        if args.embedding_model_max_context is not None and args.embedding_model_max_context < 0:
            parser.error("Local embedding context must be nonnegative (0 uses the model's context).")
        if args.llama_embedding_idle_timeout is not None and (
            not math.isfinite(args.llama_embedding_idle_timeout) or args.llama_embedding_idle_timeout <= 0
        ):
            parser.error("--llama-embedding-idle-timeout must be a positive finite number.")

    # Set logging level
    logging.root.setLevel(args.log_level.upper())

    api_models_selected = bool(
        args.model or args.helper_model or args.embedding_model
    )
    api_key = "NO_AUTH"
    if args.auth and api_models_selected:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

    auth = OpenAIAuthConfig(
        base_url=os.getenv("OPENAI_BASE_URL", args.api_url),
        api_key=api_key
    )

    model = (
        LlamaLanguageModelConfig(
            hf_repo=args.llama_hf,
            hf_file=args.llama_file,
            binary=args.llama_binary or "llama-server",
            max_context=args.model_max_context,
            idle_timeout=60.0 if args.llama_idle_timeout is None else args.llama_idle_timeout,
        )
        if args.llama_hf else
        OpenAILanguageModelConfig(id=args.model, max_context=args.model_max_context)
    )

    helper_model = (
        LlamaLanguageModelConfig(
            hf_repo=args.llama_helper_hf,
            hf_file=args.llama_helper_file,
            binary=args.llama_helper_binary or "llama-server",
            max_context=args.helper_model_max_context,
            idle_timeout=60.0 if args.llama_helper_idle_timeout is None else args.llama_helper_idle_timeout,
        )
        if args.llama_helper_hf else
        OpenAILanguageModelConfig(id=args.helper_model, max_context=args.helper_model_max_context)
        if args.helper_model else None
    )

    embedding_model = None
    if args.llama_embedding_hf:
        embedding_model = LlamaEmbeddingModelConfig(
            hf_repo=args.llama_embedding_hf,
            hf_file=args.llama_embedding_file,
            binary=args.llama_embedding_binary or "llama-server",
            max_context=0 if args.embedding_model_max_context is None else args.embedding_model_max_context,
            min_chunk_size=args.embedding_model_min_size,
            max_chunk_size=args.embedding_model_max_size,
            idle_timeout=60.0 if args.llama_embedding_idle_timeout is None else args.llama_embedding_idle_timeout,
        )
    elif args.embedding_model:
        embedding_model = OpenAIEmbeddingModelConfig(
            id=args.embedding_model,
            max_context=16192 if args.embedding_model_max_context is None else args.embedding_model_max_context,
            dimension=768 if args.embedding_model_dimension is None else args.embedding_model_dimension,
            min_chunk_size=args.embedding_model_min_size,
            max_chunk_size=args.embedding_model_max_size,
        )

    features = PixiFeatures(0)
    if args.tool_calling:
        features |= PixiFeatures.ToolCalling
    if args.tool_logging:
        features |= PixiFeatures.ToolLogging
    if args.wiki_search:
        features |= PixiFeatures.WikiSearch
    if args.gif_search:
        features |= PixiFeatures.GIFSearch
    if args.image_support:
        features |= PixiFeatures.ImageSupport
    if args.audio_support:
        features |= PixiFeatures.AudioSupport
    if args.news_feed_url:
        features |= PixiFeatures.NewsProactive

    datasets = []
    for name in args.database_names:
        datasets.append(DatasetConfig(name=name))

    wikis = []
    for nameurl in args.mediawiki_wikis:
        name, url = nameurl.split("=")
        wikis.append(MediaWikiConfig(url=url, name=name))

    if PixiFeatures.WikiSearch in features and not wikis:
        wikis = [MediaWikiConfig(
            url="https://www.wikipedia.org/w/",
            name="wikipedia"
        )]

    environment_filter = IdFilter.allow()
    if args.environment_ids:
        if args.environment_whitelist:
            environment_filter = IdFilter.whitelist(args.environment_ids)
        else:
            environment_filter = IdFilter.blacklist(args.environment_ids)

    news_config = None
    if args.news_feed_url:
        news_config = NewsConfig(
            feed_url=args.news_feed_url,
            interval_sec=args.news_interval,
            probability=args.news_probability,
        )


    from .bootstrap import create_bot

    with ExitStack() as resources:
        messages_storage = None
        if args.messages_storage == "sql":
            assert args.messages_storage_url is not None
            try:
                from .storage.sql import MessagesSQLStorage
            except ImportError:
                parser.error("SQL message storage requires pip install 'pixi-bot[sql]'.")
            messages_storage = MessagesSQLStorage(args.messages_storage_url)
            resources.callback(messages_storage.close)
        elif args.messages_storage == "redis":
            assert args.messages_storage_url is not None
            try:
                from .storage.redis import MessagesRedisStorage
            except ImportError:
                parser.error("Redis message storage requires pip install 'pixi-bot[redis]'.")
            messages_storage = MessagesRedisStorage(
                args.messages_storage_url,
                key_prefix=args.redis_key_prefix if args.redis_key_prefix is not None else "pixi:messages:",
            )
            resources.callback(messages_storage.close)

        cache_storage = None
        if args.cache_storage == "sql":
            assert args.cache_storage_url is not None
            try:
                from .caching.sql import CacheSQLStorage
            except ImportError:
                parser.error("SQL caching requires pip install 'pixi-bot[sql]'.")
            cache_storage = CacheSQLStorage(args.cache_storage_url)
            resources.callback(cache_storage.close)
        elif args.cache_storage == "redis":
            assert args.cache_storage_url is not None
            try:
                from .caching.redis import CacheRedisStorage
            except ImportError:
                parser.error("Redis caching requires pip install 'pixi-bot[redis]'.")
            cache_storage = CacheRedisStorage(
                args.cache_storage_url,
                key_prefix=(
                    args.cache_redis_key_prefix if args.cache_redis_key_prefix is not None
                    else "pixi:cache:"
                ),
            )
            resources.callback(cache_storage.close)

        return create_bot(
            platform=Platform[args.platform.upper()],
            auth=auth,
            model=model,
            helper_model=helper_model,
            embedding_model=embedding_model,
            features=features,
            datasets=datasets,
            wikis=wikis,
            environment_filter=environment_filter,
            news_config=news_config,
            directory=args.pixi_directory,
            instance_idle_timeout=args.instance_idle_timeout,
            messages_storage=messages_storage,
            cache_storage=cache_storage,
        ).run()
