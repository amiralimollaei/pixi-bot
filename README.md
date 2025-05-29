# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

A small, hackable and powerful AI chatbot implementation with tool calling and image support that blends in perfectly with the users.

## Features

- **Multi-platform support:** Works with Discord and Telegram out of the box.
- **Tool calling:** Supports calling external tools and APIs from chat.
- **Image support:** Can generate, cache, and send images.
- **Audio support:** Can cache and send audio responses.
- **Persona customization:** Easily modify the bot's persona and behavior.
- **Extensible:** Easily add new commands, tools, or integrations.
- **Environment variable and dotenv support:** Securely manage API keys and tokens.

## Requirements

- Python >= 3.10
- openai (`pip install openai`)
- pillow (for image caching, `pip install pillow`)
- ffmpegio (for audio caching, `pip install ffmpegio`)

## Usage

### For Discord

- Install `discord.py` using `pip install discord.py`
- Set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- Run `python main.py --platform discord`

### For Telegram

- Install `python-telegram-bot` using `pip install "python-telegram-bot"`
- Set `DEEPINFRA_API_KEY` environment variable and `TELEGRAM_BOT_TOKEN`
- Run `python main.py --platform telegram`

### Using dotenv

- Install `dotenv` using `pip install dotenv`
- Create a `.env` file and set `DEEPINFRA_API_KEY`, `DISCORD_BOT_TOKEN` and `TELEGRAM_BOT_TOKEN` environment variables inside the file then run the main python files.

### Example Commands & Usages

- **Chatting:**
  - Send a message and get an AI-powered response.
- **Image Generation:**
  - Use `/image <prompt>` to generate and receive images.
- **Audio Responses:**
  - The bot can reply with audio if enabled.
- **Custom Commands:**
  - Add your own commands in the `pixi/commands.py` file.
- **Persona:**
  - Edit `persona.json` to change the bot's personality.

For more advanced usage and customization, see the code and comments in the `pixi/` directory.
