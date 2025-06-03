import logging

from pixi.enums import Platform
from pixi.utils import Ansi
from pixi.client import PixiClient

logging.basicConfig(
    format=f"{Ansi.GREY}[{Ansi.BLUE}%(asctime)s{Ansi.GREY}] {Ansi.GREY}[{Ansi.YELLOW}%(levelname)s / %(name)s{Ansi.GREY}] {Ansi.WHITE}%(message)s",
    level=logging.INFO
)

# https://github.com/langchain-ai/langchain/issues/14065#issuecomment-1834571761
# Get the logger for 'httpx'
httpx_logger = logging.getLogger("httpx")
# Set the logging level to WARNING to ignore INFO and DEBUG logs
httpx_logger.setLevel(logging.WARNING)


def run(
    platform: Platform,
    *,
    model: str,
    helper_model: str,
    api_url: str,
    database_names: list[str] | None = None,
    enable_tool_calls=True,
    log_tool_calls=False
):
    # create an instance of the bot and run it
    client = PixiClient(
        platform=platform,
        model=model,
        helper_model=helper_model,
        api_url=api_url,
        database_names=database_names,
        enable_tool_calls=enable_tool_calls,
        log_tool_calls=log_tool_calls
    )
    client.run()


if __name__ == '__main__':
    from pixi.utils import load_dotenv

    import argparse
    import multiprocessing

    # load environment variables
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run the Pixi bot, a multi-platform AI chatbot.")
    parser.add_argument(
        "--platform", "-p",
        type=str,
        choices=[p.name.lower() for p in Platform] + ["all"],
        required=True,
        help="Platform to run the bot on."
    )
    parser.add_argument(
        "--log-level", "-l",
        type=str,
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Set the logging level."
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default="google/gemini-2.5-pro",
        help="Model to use for the bot. Default is 'google/gemini-2.5-pro`."
    )
    parser.add_argument(
        "--helper-model",
        type=str,
        default="google/gemini-2.5-flash",
        help="Model to use for agentic tools. Default is 'google/gemini-2.5-flash`."
    )
    parser.add_argument(
        "--api-url", "-a",
        type=str,
        default="https://api.deepinfra.com/v1/openai",
        help="OpenAI Compatible API URL to use for the bot. Default is 'https://api.deepinfra.com/v1/openai'."
    )
    parser.add_argument(
        "--disable-tool-calls",
        action="store_true",
        help="Disable tool calls"
    )
    parser.add_argument(
        "--log-tool-calls",
        action="store_true",
        help="Enable logging for tool calls (enabled by default when running with logging level DEBUG)"
    )
    parser.add_argument(
        "--database-names", "-d",
        type=str,
        nargs="+",
        default=None,
        help="add the name of databases to use (space-separated)."
    )
    args = parser.parse_args()

    # Set logging level
    logging.getLogger().setLevel(args.log_level.upper())

    client_args = dict(
        model=args.model,
        helper_model=args.helper_model,
        api_url=args.api_url,
        enable_tool_calls=not args.disable_tool_calls,
        database_names=args.database_names,
        log_tool_calls=args.log_tool_calls
    )

    try:
        processes = []
        platform = args.platform.upper()
        if platform == "ALL":
            for plat in Platform:
                poc = multiprocessing.Process(target=run, kwargs=dict(platform=plat, **client_args))
                poc.start()
                processes.append(poc)
            for poc in processes:
                poc.join()
        else:
            run(platform=Platform[platform], **client_args)
    except KeyboardInterrupt:
        logging.info("Shutting down the bot.")
        for process in processes:
            process.join()
