# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

A small, hackable and powerful AI chatbot implementation with tool calling and image support that blends in perfectly with the users.

## Features

- **Multi-platform support:** Works with Discord and Telegram out of the box.
- **Tool calling:** Supports calling external tools and APIs from chat.
- **Image support:** Can recieve, compress and cache images.
- **Audio support:** Can recieve, compress and cache audio.
- **Persona configuration:** Easily modify the bot's persona and behavior.
- **Addon Support:** Easily add new commands, tools, or other integrations (WIP, API is unstable and documentation is pending).
- **Environment variable:** Securely manage API keys and tokens with dotenv support.

## Requirements

- Python >= 3.11
- aiofiles>=25.1.0
- argparse>=1.4.0
- dotenv>=0.9.9
- openai>=2.8.1
- zstandard>=0.25.0
- discord-py>=2.6.4 (optional, for discord platform)
- python-telegram-bot>=22.5  (optional, for telegram platform)
- av>=16.0.0 (optional, for media caching)
- uv (optional, for setting up the requirements automatically in a venv)

## Getting Started

there are 3 extra optional dependecy groups that you may need to install based on your own needs:

- media: installs PyAV and enables media caching and processing features
- discord: installs discord.py and enables discord bot functionality
- telegram: installs python-telegram-bot and enables telegram bot functionality

you have to install at least one of the dependecy groups for a social media platform, this guide shows you how to install all modules at once

### Installation using PIP

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
pip install .[media,discord,telegram]
```

### Installation using UV

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
uv sync --all-extras
```

### Setup Environment Variables

- Create a `.env` file and set `OPENAI_API_KEY` to your API provider's API Key (prevously was `DEEPINFRA_API_KEY`)
- Set `DISCORD_BOT_TOKEN` and/or `TELEGRAM_BOT_TOKEN` environment variables
- Set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- Optionally set `GIPHY_API_KEY` for GIF search features

### Runninig The Bot

- discord: `pixi-cli -p discord [options]`
- telegram: `pixi-cli -p telegram [options]`

> NOTE: if you've installed this project using UV you should run `uv run pixi-cli` instead of just `pixi-cli`
> or run `source ./venv/bin/activate` before running the above commands

## CLI Usage

> the following message is provided by running `pixi-cli --help`

```text
usage: pixi-cli [-h] --platform {discord,telegram}
                [--log-level {debug,info,warning,error,critical}] [--api-url API_URL]
                [--auth | --no-auth] --model MODEL
                [--model-max-context MODEL_MAX_CONTEXT] [--helper-model HELPER_MODEL]
                [--helper-model-max-context HELPER_MODEL_MAX_CONTEXT]
                [--embedding-model EMBEDDING_MODEL]
                [--embedding-model-max-context EMBEDDING_MODEL_MAX_CONTEXT]
                [--embedding-model-dimension EMBEDDING_MODEL_DIMENSION]
                [--embedding-model-split-size EMBEDDING_MODEL_SPLIT_SIZE]
                [--embedding-model-min-size EMBEDDING_MODEL_MIN_SIZE]
                [--embedding-model-max-size EMBEDDING_MODEL_MAX_SIZE]
                [--embedding-model-sentence-level | --no-embedding-model-sentence-level | -esent]
                [--tool-calling | --no-tool-calling]
                [--tool-logging | --no-tool-logging]
                [--wiki-search | --no-wiki-search] [--gif-search | --no-gif-search]
                [--image-support | --no-image-support]
                [--audio-support | --no-audio-support]
                [--environment-whitelist | --no-environment-whitelist]
                [--environment-ids ENVIRONMENT_IDS [ENVIRONMENT_IDS ...]]
                [--database-names DATABASE_NAMES [DATABASE_NAMES ...]]

Run the Pixi bot, a multi-platform AI chatbot.

options:
  -h, --help            show this help message and exit
  --platform, -p {discord,telegram}
                        Platform to run the bot on.
  --log-level, -l {debug,info,warning,error,critical}
                        Set the logging level.
  --api-url, -a API_URL
                        OpenAI Compatible API URL to use for the bot
  --auth, --no-auth     whether or not to authorize to the API backends
  --model, -m MODEL     Language Model to use for the main chatbot bot
  --model-max-context, -ctx MODEL_MAX_CONTEXT
                        Maximum model context size (in tokens), pixi tries to
                        apporiximately stay within this context size, Default is
                        '16192`.
  --helper-model, -hm HELPER_MODEL
                        Language Model to use for agentic tools
  --helper-model-max-context, -hctx HELPER_MODEL_MAX_CONTEXT
                        Maximum helper model context size (in tokens), pixi tries to
                        apporiximately stay within this context size, Default is
                        '16192`.
  --embedding-model, -em EMBEDDING_MODEL
                        Embedding Model to use for embedding tools
  --embedding-model-max-context, -ectx EMBEDDING_MODEL_MAX_CONTEXT
                        Maximum embedding model context size (in tokens), pixi tries
                        to apporiximately stay within this context size, Default is
                        '16192`.
  --embedding-model-dimension, -ed EMBEDDING_MODEL_DIMENSION
                        Dimention to use for the embedding model, Default is '768`.
  --embedding-model-split-size, -esplit EMBEDDING_MODEL_SPLIT_SIZE
                        Split size to use for the embedding chunk tokenizer, Default
                        is '1024`.
  --embedding-model-min-size, -emin EMBEDDING_MODEL_MIN_SIZE
                        Minimum chunk size to use for the embedding chunk tokenizer,
                        Default is '256`.
  --embedding-model-max-size, -emax EMBEDDING_MODEL_MAX_SIZE
                        Maximum chunk size to use for the embedding chunk tokenizer,
                        Default is '256`.
  --embedding-model-sentence-level, --no-embedding-model-sentence-level, -esent
                        whether or not the embedding model is a sentence level
                        embedding model, Default is 'False`.
  --tool-calling, --no-tool-calling
                        allows pixi to use built-in and/or plugin tools, tool calling
                        can only be used if the model supports them
  --tool-logging, --no-tool-logging
                        verbose logging for tool calls (enabled by default when
                        running with logging level DEBUG)
  --wiki-search, --no-wiki-search
                        allows pixi to search any mediawiki compatible Wiki
  --gif-search, --no-gif-search
                        allows pixi to search for gifs online, and send them in chat
  --image-support, --no-image-support
                        allows pixi to download and process image files
  --audio-support, --no-audio-support
                        allows pixi to download and process audio files
  --environment-whitelist, --no-environment-whitelist
                        whether or not the ids passed to --filter-environment-ids are
                        whitelisted or blacklisted
  --environment-ids ENVIRONMENT_IDS [ENVIRONMENT_IDS ...]
                        add the id of the environment that the bot is or is not
                        allowed to respond in (space-separated). If not provided, the
                        bot will respond everywhere.
  --database-names, -d DATABASE_NAMES [DATABASE_NAMES ...]
                        add the name of databases to use (space-separated).
```

## Lisence

MIT
