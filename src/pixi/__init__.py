__author__ = "amiralimollaei"


def main():
    import argparse
    import logging
    import os

    from .storage.paths import PixiPaths, copy_default_resources

    from .model.enums.ansi import AnsiColors
    from .utils import load_dotenv
    
    from .model.enums import Platform
    from .model.config import (DatasetConfig, IdFilter, MediaWikiConfig,
                            NewsConfig, OpenAIAuthConfig,
                            OpenAIEmbeddingModelConfig, OpenAILanguageModelConfig,
                            PixiFeatures)

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
        help="Save and unload inactive conversations after this many seconds (default: 900)."
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
    parser.add_argument(
        "--model", "-m",
        type=str,
        required=True,
        help="Language Model to use for the main chatbot bot"
    )
    parser.add_argument(
        "--model-max-context", "-ctx",
        type=int,
        default=16192,
        help="Maximum model context size (in tokens), pixi tries to apporiximately stay within this context size, Default is '16192`."
    )

    # helper model arguments
    parser.add_argument(
        "--helper-model", "-hm",
        type=str,
        help="Language Model to use for agentic tools"
    )
    parser.add_argument(
        "--helper-model-max-context", "-hctx",
        type=int,
        default=16192,
        help="Maximum helper model context size (in tokens), pixi tries to apporiximately stay within this context size, Default is '16192`."
    )

    # embedding model arguments
    parser.add_argument(
        "--embedding-model", "-em",
        type=str,
        help="Embedding Model to use for embedding tools"
    )
    parser.add_argument(
        "--embedding-model-max-context", "-ectx",
        type=int,
        default=16192,
        help="Maximum embedding model context size (in tokens), pixi tries to apporiximately stay within this context size, Default is '16192`."
    )
    parser.add_argument(
        "--embedding-model-dimension", "-ed",
        type=int,
        default=768,
        help="Dimension to use for the embedding model, Default is '768`."
    )
    parser.add_argument(
        "--embedding-model-min-size", "-emin",
        type=int,
        default=256,
        help="Minimum chunk size to use for the embedding chunk tokenizer, Default is '256`."
    )
    parser.add_argument(
        "--embedding-model-max-size", "-emax",
        type=int,
        default=1024,
        help="Maximum chunk size to use for the embedding chunk tokenizer, Default is '1024`."
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

    # Set logging level
    logging.root.setLevel(args.log_level.upper())

    api_key = "NO_AUTH"
    if args.auth:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

    auth = OpenAIAuthConfig(
        base_url=os.getenv("OPENAI_BASE_URL", args.api_url),
        api_key=api_key
    )

    model = OpenAILanguageModelConfig(
        id=args.model,
        max_context=args.model_max_context,
    )

    helper_model = OpenAILanguageModelConfig(
        id=args.helper_model,
        max_context=args.helper_model_max_context,
    ) if args.helper_model else None

    embedding_model = OpenAIEmbeddingModelConfig(
        id=args.embedding_model,
        max_context=args.embedding_model_max_context,
        dimension=args.embedding_model_dimension,
        min_chunk_size=args.embedding_model_min_size,
        max_chunk_size=args.embedding_model_max_size,
    ) if args.embedding_model else None

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

    PixiPaths.set_root(args.pixi_directory)
    copy_default_resources()

    from .bot.client import PixiClient  # shouldn't have to be imported after PixiPaths.set_root but just in case

    return PixiClient(
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
        instance_idle_timeout=args.instance_idle_timeout,
    ).run()
