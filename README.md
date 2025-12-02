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
- discord-py>=2.6.4
- dotenv>=0.9.9
- openai>=2.8.1
- python-telegram-bot>=22.5
- zstandard>=0.25.0
- pillow>=12.0.0 (optional, for image caching)
- ffmpegio>=0.11.1 (optional, for audio caching)
- UV (optional, for setting up the requirements automatically in a venv)

## Getting Started

there are 4 extra optional dependecy groups that you may need to install based on your own needs:

- image: installs pillow and enables audio caching features
- audio: installs ffmpegio and enables image caching features
- discord: installs discord.py and enables discord bot functionality
- telegram: installs python-telegram-bot and enables telegram bot functionality

you have to install at least one of the dependecy groups for a social media platform, this guide shows you how to install all modules at once

### Installation using PIP

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
pip install .[image,audio,discord,telegram]
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
usage: pixi-cli [-h] --platform {discord,telegram} [--log-level {debug,info,warning,error,critical}] [--model MODEL]
                [--helper-model HELPER_MODEL] [--api-url API_URL] [--disable-tool-calls] [--disable-images] [--disable-audio]
                [--log-tool-calls] [--database-names DATABASE_NAMES [DATABASE_NAMES ...]]
                [--allowed-places ALLOWED_PLACES [ALLOWED_PLACES ...]]

Run the Pixi bot, a multi-platform AI chatbot.

options:
  -h, --help            show this help message and exit
  --platform {discord,telegram}, -p {discord,telegram}
                        Platform to run the bot on.
  --log-level {debug,info,warning,error,critical}, -l {debug,info,warning,error,critical}
                        Set the logging level.
  --model MODEL, -m MODEL
                        Model to use for the bot. Default is 'google/gemini-2.5-pro`.
  --helper-model HELPER_MODEL, -hm HELPER_MODEL
                        Model to use for agentic tools. Default is 'google/gemini-2.5-flash`.
  --api-url API_URL, -a API_URL
                        OpenAI Compatible API URL to use for the bot. Default is 'https://api.deepinfra.com/v1/openai'.
  --disable-tool-calls  Disable tool calls
  --disable-images      Disable accepting images
  --disable-audio       Disable accepting audio
  --log-tool-calls      Enable logging for tool calls (enabled by default when running with logging level DEBUG)
  --database-names DATABASE_NAMES [DATABASE_NAMES ...], -d DATABASE_NAMES [DATABASE_NAMES ...]
                        add the name of databases to use (space-separated).
  --allowed-places ALLOWED_PLACES [ALLOWED_PLACES ...]
                        add the name of places that the bot is allowed to respond in (space-separated). If not provided, the bot
                        will respond everywhere.
```

## Lisence

MIT
