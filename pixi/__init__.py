__author__ = "amiralimollaei"

import os
from pathlib import Path

from .config import OpenAIAuthConfig, OpenAIEmbeddingModelConfig, OpenAILanguageModelConfig, PixiFeatures, IdFilter, DatasetConfig
from .enums import Platform
from .utils import PixiPaths, Ansi, copy_default_resources, load_dotenv


def run(
    platform: Platform,
    pixi_directory: str | Path,
    *,
    auth: OpenAIAuthConfig,
    model: OpenAILanguageModelConfig,
    helper_model: OpenAILanguageModelConfig | None,
    embedding_model: OpenAIEmbeddingModelConfig | None,
    features: PixiFeatures = PixiFeatures.empty(),
    environment_filter: IdFilter = IdFilter.allow(),
    datasets: list[DatasetConfig] = [],
):
    PixiPaths.set_root(pixi_directory)
    copy_default_resources()

    from .client import PixiClient  # shouldn't have to be imported after PixiPaths.set_root but just in case

    PixiClient(
        platform=platform,
        auth=auth,
        model=model,
        helper_model=helper_model,
        embedding_model=embedding_model,
        features=features,
        environment_filter=environment_filter,
        datasets=datasets,
    ).run()


def main():
    import logging

    import argparse

    # injecting colors into the default logger

    COLORS = {  # (level_color, message_color)
        logging.DEBUG: (Ansi.BLUE, Ansi.BEIGE),
        logging.INFO: (Ansi.WHITE, Ansi.WHITE2),
        logging.WARNING: (Ansi.YELLOW, Ansi.YELLOW2),
        logging.ERROR: (Ansi.RED, Ansi.RED2),
        logging.CRITICAL: (Ansi.BOLD + Ansi.RED, Ansi.BOLD + Ansi.RED2)
    }

    orig_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = orig_factory(*args, **kwargs)
        level_color, message_color = COLORS.get(record.levelno, (Ansi.GREY, Ansi.WHITE))
        record.level_color = level_color
        record.message_color = message_color
        return record
    logging.setLogRecordFactory(record_factory)

    logging.basicConfig(
        format=f"{Ansi.GREY}[{Ansi.BLUE}%(asctime)s{Ansi.GREY}] {Ansi.GREY}[%(level_color)s%(levelname)s / %(name)s{Ansi.GREY}] %(message_color)s%(message)s{Ansi.END}",
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
        choices=[p.name.lower() for p in Platform],
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
        help="Dimention to use for the embedding model, Default is '768`."
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
    parser.add_argument(
        "--tool-calling",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="allows pixi to use built-in and/or plugin tools, tool calling can only be used if the model supports them"
    )
    parser.add_argument(
        "--tool-logging",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="verbose logging for tool calls (enabled by default when running with logging level DEBUG)"
    )
    parser.add_argument(
        "--wiki-search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="allows pixi to search any mediawiki compatible Wiki"
    )
    parser.add_argument(
        "--gif-search",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="allows pixi to search for gifs online, and send them in chat"
    )
    parser.add_argument(
        "--image-support",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="allows pixi to download and process image files"
    )
    parser.add_argument(
        "--audio-support",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="allows pixi to download and process audio files"
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
        "--database-names", "-d",
        type=str,
        nargs="+",
        default=[],
        help="add the name of databases to use (space-separated)."
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
        features |= PixiFeatures.EnableToolCalling
    if args.tool_logging:
        features |= PixiFeatures.EnableToolLogging
    if args.wiki_search:
        features |= PixiFeatures.EnableWikiSearch
    if args.gif_search:
        features |= PixiFeatures.EnableGIFSearch
    if args.image_support:
        features |= PixiFeatures.EnableImageSupport
    if args.audio_support:
        features |= PixiFeatures.EnableAudioSupport

    datasets = []
    for name in args.database_names:
        datasets.append(DatasetConfig(name=name))

    environment_filter = IdFilter.allow()
    if args.environment_ids:
        if args.environment_whitelist:
            environment_filter = IdFilter.whitelist(args.environment_ids)
        else:
            environment_whitelist = IdFilter.blacklist(args.environment_ids)

    return run(
        Platform[args.platform.upper()],
        pixi_directory=args.pixi_directory,
        auth=auth,
        model=model,
        helper_model=helper_model,
        embedding_model=embedding_model,
        features=features,
        environment_filter=environment_filter,
        datasets=datasets,
    )
