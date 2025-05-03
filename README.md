# Pixi AI Chatbot

A highly customzable and powerful AI chatbot that blends in perfectly with the users, with tool calling and image support

## usage

**For Discord**:

- set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- install `discord.py` using `pip install discord.py`
- run `python main-discord.py`

**For Telegram**:

- set `DEEPINFRA_API_KEY` environment variable and `TELEGRAM_BOT_TOKEN`
- install `python-telegram-bot` using `pip install "python-telegram-bot[job-queue]"`
- run `python main-telegram.py`

**using dotenv**

create a `.env` file and set DEEPINFRA_API_KEY, DISCORD_BOT_TOKEN and TELEGRAM_BOT_TOKEN environment variables inside the file then run the main python files.
