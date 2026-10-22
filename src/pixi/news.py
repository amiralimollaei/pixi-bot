import asyncio
import json
import logging
import random
from typing import Optional

from .apis.rss import AsyncRSSAPI
from .chatting import AsyncChatbotInstance
from .model.config.news import NewsConfig
from .model.enums import ChatRole
from .model.storage.message import ChatMessageMeta
from .platform import PlatformProvider
from .storage.paths import open_resource


class NewsBackgroundTask:
    """
    Background task that periodically checks world news and proactively sends
    conversation starters to an appropriate forum channel.
    """

    def __init__(
        self,
        news_config: NewsConfig,
        reflection_api: PlatformProvider,
        instance: AsyncChatbotInstance,
    ):
        self.logger = logging.getLogger(f"{self.__class__.__name__}[{instance.id}]")
        self.news_config = news_config
        self.reflection_api = reflection_api
        self.instance = instance
        self.feed_api = AsyncRSSAPI(self.news_config.feed_url)
        self.channel_blacklist: list[int] = []

        with open_resource("news-system.md", "r") as f:
            self.system_prompt_template: str = f.read()

        self._task: Optional[asyncio.Task] = None

    def start(self):
        """Start the background news task."""
        if self._task is not None and not self._task.done():
            self.logger.warning("News background task is already running.")
            return
        self._task = asyncio.create_task(self._run(), name=f"news-task-{self.instance.id}")

    def stop(self):
        """Stop the background news task."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            self.logger.info("News background task cancelled.")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self):
        with self.instance.use():
            interval_seconds = self.news_config.interval_sec
            while True:
                try:
                    await asyncio.sleep(interval_seconds)

                    # Probability check
                    if random.random() >= self.news_config.probability:
                        self.logger.debug("Probability check missed, skipping this cycle.")
                        continue

                    await self._execute_news_cycle()

                except asyncio.CancelledError:
                    self.logger.info("News background task cancelled.")
                    raise
                except Exception:
                    self.logger.exception("Unexpected error in news background task.")

    async def _execute_news_cycle(self):
        """Fetch news, generate a message, pick a channel, and send it."""
        self.logger.info(f"News cycle triggered")

        channels = []
        forum_id = self.instance.forum_id
        if forum_id is not None:
            channels = await self.reflection_api.fetch_forum_channels(forum_id)
            if not channels:
                self.logger.warning(f"No channels found for forum {forum_id}.")
                return
        else:
            self.logger.warning(f"News cycle cancelled")
            return

        # 1. Fetch news
        headlines = await self.feed_api.fetch(max_items=10)
        if not headlines:
            self.logger.warning("No news headlines fetched.")
            return

        # 2. Generate a conversation starter message via the instance's LLM
        prompt = self.system_prompt_template.format(
            persona=self.instance.persona,
            realtime=self.instance.get_realtime_data(),
        ) + (
            "[SYSTEM] Start a casual conversation in a channel. (this is seperate from your current conversation) "
            "React to one or more of these news headlines in a natural, engaging way that would make others want to join the discussion. "
            "| title | summary |\n"
            "|---|---|\n"
            "\n".join([f"{headline.title} | {headline.summary}" for headline in headlines]) + "\n\n"
            "[SYSTEM] You must also choose a channel the message will be sent to, choose carefully, make sure the channel ID (number) is valid."
            "Available Channels:\n"
            "\n".join([" - " + str(c.id) for c in channels]) + "\n\n"
            "Output a valid json, with no formatting or markdown, with the following json schema:\n"
            "```json\n"
            "{\"message\": <your-reaction>, \"channel\": <channel-id-number>}"
            "```"
        )

        message_text = ""
        async for char in self.instance.stream_ask(message="[SYSTEM] Write your message:", temporal=True, system_prompt=prompt):
            message_text += char

        message_text = message_text.strip()
        if not message_text:
            self.logger.warning("Generated empty message, skipping.")
            return
        response = None
        try:
            response = json.loads(message_text.removeprefix("```json").removesuffix("```").strip())
        except Exception:
            self.logger.exception("Generated invalid message, skipping.")

        assert response

        self.logger.info(f"Generated message: {message_text}...")

        # 3. Select appropriate channel

        forum_id = self.instance.forum_id
        if forum_id is None:
            channel_id = self.instance.chat_id
        else:
            channel_id = int(response["channel"])

        assert channel_id

        # 4. Send the message
        try:
            message_text = response["message"]
            # pyright: ignore[reportArgumentType]
            await self.reflection_api.send_message(chat_id=channel_id, text=message_text)
            self.logger.info(f"Sent proactive news message to channel {channel_id}.")
            # update instance
            self.instance.add_message(ChatMessageMeta(ChatRole.ASSISTANT, content=f"[send: {message_text}]"))
            await self.instance.cancel_channel_active_tasks(channel_id=str(channel_id))
            self.instance.save()
        except RuntimeError:
            self.channel_blacklist.append(channel_id)
            self.logger.exception(f"Failed to send message to channel {channel_id}, retrying in 10 seconds...")

            await asyncio.sleep(10)
            await self._execute_news_cycle()
