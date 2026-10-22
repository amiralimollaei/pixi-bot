# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

A small, hackable and powerful AI chatbot implementation with tool calling and image support that blends in perfectly with the users.

## Features

- **Multi-Platform Support:** Works with Discord and Telegram out of the box.
- **Configurable:** Easily modify the bot's persona and behavior.
- **Change Data Directory:** Run multiple instances with completely different configurations/storage in parallel.
- **Tool Calling:** Supports calling external tools and APIs from chat.
- **Advanced Logging:** Colored logging, Supports logging tool calls and extra information for debugging.
- **Image Support:** Can recieve, compress and cache all image formats.
- **Audio Support:** Can recieve, compress and cache all audio formats.
- **Addon Support:** Easily add new actions, tools, or other integrations (WIP, API is unstable and documentation is pending).
- **Dotenv Support:** Securely manage API keys and tokens with environment variables.

## Requirements

- Python>=3.12
- dotenv
- openai
- zstandard
- discord-py (optional, for discord platform)
- python-telegram-bot  (optional, for telegram platform)
- ffmpeg (on `PATH`, for default media caching)
- av (legacy fallback for when ffmpeg is not available)
- uv (recommended, for setting up all the requirements easily in a python virtual environemnt)

## Getting Started

There are many extra optional dependecy groups that you may need to install based on your own needs, for simplicity, this guide shows you how to install all modules at once.

| extra dependecy group | packages | description | status |
|---|---|---|:---:|
| media | av | installs the optional PyAV compatibility backend; default caching uses the system FFmpeg executable | optional |
| discord | discord-py | installs discord.py and enables discord bot functionality | optional\* |
| telegram | python-telegram-bot | installs python-telegram-bot and enables telegram bot functionality | optional\* |

> \[\*\] you have to install at least one of these dependecy groups for the bot to function

You should also have your own OpenAI compatible API URL and API Key and provide that to pixi, using the command line interface and/or environment variables
and you should also choose a large langauge model to use for the bot and optionally a seperate one for agentic tools, e.g. online/offline search tools, based on my testing, it works best with `google/gemini-2.0-flash-001`, works best with agentic models.
optionally you may also choose an embedding model to process web search or offline search content, works best with `BAAI/bge-m3-multi` but you can use any other model.

### Installation using UV (Recommended)

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
uv sync --all-extras
# enter the venv
source .venv/bin/activate
# run using pixi-cli -p [platform] [options]
```

### CLI Usage with UVX (Recommended)

You can combine the process of installing and/or updating requirements and pixi, and running it into a single command:

```sh
# for telegram
# installs pixi-bot from pypi, updates it, and runs pixi-cli
uvx --env-file .env pixi-bot[telegram,media]@latest -p telegram [options]
```

```sh
# for discord
# installs pixi-bot from pypi, updates it, and runs pixi-cli
uvx --env-file .env pixi-bot[discord,media]@latest -p discord [options]
```

### Installation using PIP

```sh
pip install pixi-bot[media,discord,telegram]
pixi-cli -p [platform] [options]
```

### Setup Environment Variables

- Create a `.env` file and set `OPENAI_API_KEY` to your API provider's API Key
- Set `DISCORD_BOT_TOKEN` and/or `TELEGRAM_BOT_TOKEN` environment variables
- Set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- Optionally set `TENOR_API_KEY` for GIF search features powered by Tenor

### Runninig The Bot

- Discord: `pixi-cli -p discord [options]`
- Telegram: `pixi-cli -p telegram [options]`

## CLI Usage

> the following message is provided by running `pixi-cli --help`

```text
usage: pixi-cli [-h] --platform {discord,telegram}
                [--pixi-directory PIXI_DIRECTORY]
                [--log-level {debug,info,warning,error,critical}]
                [--instance-idle-timeout INSTANCE_IDLE_TIMEOUT]
                [--api-url API_URL] [--auth | --no-auth] --model MODEL
                [--model-max-context MODEL_MAX_CONTEXT]
                [--helper-model HELPER_MODEL]
                [--helper-model-max-context HELPER_MODEL_MAX_CONTEXT]
                [--embedding-model EMBEDDING_MODEL]
                [--embedding-model-max-context EMBEDDING_MODEL_MAX_CONTEXT]
                [--embedding-model-dimension EMBEDDING_MODEL_DIMENSION]
                [--embedding-model-min-size EMBEDDING_MODEL_MIN_SIZE]
                [--embedding-model-max-size EMBEDDING_MODEL_MAX_SIZE]
                [--tool-calling | --no-tool-calling]
                [--tool-logging | --no-tool-logging]
                [--wiki-search | --no-wiki-search]
                [--gif-search | --no-gif-search]
                [--image-support | --no-image-support]
                [--audio-support | --no-audio-support]
                [--news-feed-url NEWS_FEED_URL]
                [--news-interval NEWS_INTERVAL]
                [--news-probability NEWS_PROBABILITY]
                [--environment-whitelist | --no-environment-whitelist]
                [--environment-ids ENVIRONMENT_IDS [ENVIRONMENT_IDS ...]]
                [--database-names DATABASE_NAMES [DATABASE_NAMES ...]]
                [--mediawiki-wikis MEDIAWIKI_WIKIS [MEDIAWIKI_WIKIS ...]]

Run the Pixi bot, a multi-platform AI chatbot.

options:
  -h, --help            show this help message and exit
  --platform, -p {discord,telegram}
                        Platform to run the bot on.
  --pixi-directory, -pd PIXI_DIRECTORY
                        The root directory for configuration files,
                        addons, userdata, assets and cache, defaults to
                        "~/.pixi/"
  --log-level, -l {debug,info,warning,error,critical}
                        Set the logging level.
  --instance-idle-timeout INSTANCE_IDLE_TIMEOUT
                        Save and unload inactive conversations after this many
                        seconds (default: 900).
  --api-url, -a API_URL
                        OpenAI Compatible API URL to use for the bot
  --auth, --no-auth     whether or not to authorize to the API backends
  --model, -m MODEL     Language Model to use for the main chatbot bot
  --model-max-context, -ctx MODEL_MAX_CONTEXT
                        Maximum model context size (in tokens), pixi
                        tries to apporiximately stay within this
                        context size, Default is '16192`.
  --helper-model, -hm HELPER_MODEL
                        Language Model to use for agentic tools
  --helper-model-max-context, -hctx HELPER_MODEL_MAX_CONTEXT
                        Maximum helper model context size (in tokens),
                        pixi tries to apporiximately stay within this
                        context size, Default is '16192`.
  --embedding-model, -em EMBEDDING_MODEL
                        Embedding Model to use for embedding tools
  --embedding-model-max-context, -ectx EMBEDDING_MODEL_MAX_CONTEXT
                        Maximum embedding model context size (in
                        tokens), pixi tries to apporiximately stay
                        within this context size, Default is '16192`.
  --embedding-model-dimension, -ed EMBEDDING_MODEL_DIMENSION
                        Dimension to use for the embedding model,
                        Default is '768`.
  --embedding-model-min-size, -emin EMBEDDING_MODEL_MIN_SIZE
                        Minimum chunk size to use for the embedding
                        chunk tokenizer, Default is '256`.
  --embedding-model-max-size, -emax EMBEDDING_MODEL_MAX_SIZE
                        Maximum chunk size to use for the embedding
                        chunk tokenizer, Default is '1024`.
  --tool-calling, --no-tool-calling
                        allows pixi to use built-in and/or plugin
                        tools, tool calling can only be used if the
                        model supports them
  --tool-logging, --no-tool-logging
                        verbose logging for tool calls (enabled by
                        default when running with logging level DEBUG)
  --wiki-search, --no-wiki-search
                        allows pixi to search any mediawiki compatible
                        Wiki
  --gif-search, --no-gif-search
                        allows pixi to search for gifs online, and send
                        them in chat
  --image-support, --no-image-support
                        allows pixi to download and process image files
  --audio-support, --no-audio-support
                        allows pixi to download and process audio files
  --news-feed-url, -n NEWS_FEED_URL
                        RSS/Atom feed URL for proactive news feature.
                        Enables the news feature if provided.
  --news-interval NEWS_INTERVAL
                        Seconds between news checks for proactive news
                        feature. Default is 3600 (1 hour).
  --news-probability NEWS_PROBABILITY
                        Probability of sending a proactive news message
                        each check (0.0 to 1.0). Default is 0.1.
  --environment-whitelist, --no-environment-whitelist
                        whether or not the ids passed to environment
                        ids are whitelisted or blacklisted
  --environment-ids ENVIRONMENT_IDS [ENVIRONMENT_IDS ...]
                        add the id of the environment that the bot is
                        or is not allowed to respond in (space-
                        separated). If not provided, the bot will
                        respond everywhere.
  --database-names, -db DATABASE_NAMES [DATABASE_NAMES ...]
                        add the name of databases to use (space-
                        separated).
  --mediawiki-wikis, -mw MEDIAWIKI_WIKIS [MEDIAWIKI_WIKIS ...]
                        add the mediawiki wikis to use (space-
                        separated), it should follow the format of
                        `name=url`, Example:
                        wikipedia=https://www.wikipedia.org/w/
```

## Lisence

MIT
