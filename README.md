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

- Python >= 3.10
- openai (`pip install openai`)
- pillow (for image caching, `pip install pillow`)
- ffmpegio (for audio caching, `pip install ffmpegio`)

## Usage

> the following message is provided by running `python main.py --help`

```shell
usage: main.py [-h] --platform {discord,telegram,all} [--log-level {debug,info,warning,error,critical}]
               [--model MODEL] [--helper-model HELPER_MODEL] [--api-url API_URL] [--disable-tool-calls]
               [--log-tool-calls] [--database-names DATABASE_NAMES [DATABASE_NAMES ...]]

Run the Pixi bot, a multi-platform AI chatbot.

options:
  -h, --help            show this help message and exit
  --platform, -p {discord,telegram,all}
                        Platform to run the bot on.
  --log-level, -l {debug,info,warning,error,critical}
                        Set the logging level.
  --model, -m MODEL     Model to use for the bot. Default is 'google/gemini-2.5-pro`.
  --helper-model HELPER_MODEL
                        Model to use for agentic tools. Default is 'google/gemini-2.5-flash`.
  --api-url, -a API_URL
                        OpenAI Compatible API URL to use for the bot. Default is
                        'https://api.deepinfra.com/v1/openai'.
  --disable-tool-calls  Disable tool calls
  --log-tool-calls      Enable logging for tool calls (enabled by default when running with logging level DEBUG)
  --database-names, -d DATABASE_NAMES [DATABASE_NAMES ...]
                        add the name of databases to use (space-separated).
```

## Getting Started

### Setup Environment Variables

- Install `dotenv` using `pip install dotenv`
- Create a `.env` file and set `OPENAI_API_KEY` to your API provider's API Key (prevously was `DEEPINFRA_API_KEY`)
- Set `DISCORD_BOT_TOKEN` and/or `TELEGRAM_BOT_TOKEN` environment variables
- Optionally set `GIPHY_API_KEY` for GIF search features

### Run Discord Bot

- Install `discord.py` using `pip install discord.py`
- Set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- Run `python main.py --platform discord`

### Run Telegram Bot

- Install `python-telegram-bot` using `pip install "python-telegram-bot"`
- Set `DEEPINFRA_API_KEY` environment variable and `TELEGRAM_BOT_TOKEN`
- Run `python main.py --platform telegram`
