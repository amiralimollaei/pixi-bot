# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

A small, hackable and powerful AI chatbot implementation with tool calling and image support that blends in perfectly with the users.

## Features

- **Multi-platform support:** Works with Discord and Telegram out of the box.
- **Tool calling:** Supports calling external tools and APIs from chat.
- **Image support:** Can generate, cache, and recieve images.
- **Audio support:** Can cache and recieve audio content.
- **Persona configuration:** Easily modify the bot's persona and behavior.
- **Extensible:** Easily add new commands, tools, or integrations.
- **Environment variable and dotenv support:** Securely manage API keys and tokens.

## Requirements

- Python >= 3.10
- openai (`pip install openai`)
- pillow (for image caching, `pip install pillow`)
- ffmpegio (for audio caching, `pip install ffmpegio`)

## Getting Started

### For Discord

- Install `discord.py` using `pip install discord.py`
- Set `OPENAI_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- Run `python main.py --platform discord -m gpt-4o`

### For Telegram

- Install `python-telegram-bot` using `pip install "python-telegram-bot"`
- Set `OPENAI_API_KEY` environment variable and `TELEGRAM_BOT_TOKEN`
- Run `python main.py --platform telegram -m gpt-4o`

### Using dotenv

- Install `dotenv` using `pip install dotenv`
- Create a `.env` file and set `OPENAI_API_KEY`, `DISCORD_BOT_TOKEN` and `TELEGRAM_BOT_TOKEN` environment variables inside the file then run the main python files.
- Optionally set `GIPHY_API_KEY` for GIF features

## Usage

> you can see the following message by running `python main.py --help`

```
usage: main.py [-h] --platform {discord,telegram,all}
               [--log-level {debug,info,warning,error,critical}] [--model MODEL]
               [--helper-model HELPER_MODEL] [--api-url API_URL] [--disable-tool-calls]
               [--database-names DATABASE_NAMES [DATABASE_NAMES ...]]

Run the Pixi bot, a multi-platform AI chatbot.

options:
  -h, --help            show this help message and exit
  --platform {discord,telegram,all}, -p {discord,telegram,all}
                        Platform to run the bot on.
  --log-level {debug,info,warning,error,critical}, -l {debug,info,warning,error,critical}
                        Set the logging level.
  --model MODEL, -m MODEL
                        Model to use for the bot. Default is 'google/gemini-2.5-pro`.
  --helper-model HELPER_MODEL
                        Model to use for agentic tools. Default is 'google/gemini-2.5-flash`.
  --api-url API_URL, -a API_URL
                        OpenAI Compatible API URL to use for the bot. Default is
                        'https://api.deepinfra.com/v1/openai'.
  --disable-tool-calls  Disable tool calls for the bot.
  --database-names DATABASE_NAMES [DATABASE_NAMES ...], -d DATABASE_NAMES [DATABASE_NAMES ...]
                        add the name of databases to use (space-separated).
```
