# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

A small, hackable and powerful AI chatbot implementation with tool calling and image support that blends in perfectly with the users.

## usage

**For Discord**:

- install `discord.py` using `pip install discord.py`
- set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- run `python main-discord.py`

**For Telegram**:

- install `python-telegram-bot` using `pip install "python-telegram-bot[job-queue]"`
- set `DEEPINFRA_API_KEY` environment variable and `TELEGRAM_BOT_TOKEN`
- run `python main-telegram.py`

**using dotenv**

create a `.env` file and set DEEPINFRA_API_KEY, DISCORD_BOT_TOKEN and TELEGRAM_BOT_TOKEN environment variables inside the file then run the main python files.
