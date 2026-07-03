import asyncio
import json
import logging
import random
from typing import Optional

from .agents import ChannelSelectorAgent
from .apis.rss import AsyncRSSAPI
from .chatting import AsyncChatbotInstance
from .model.config.news import NewsConfig
from .reflection import ReflectionAPI
from .storage.paths import open_resource


class NewsBackgroundTask:
    """
    Background task that periodically checks world news and proactively sends
    conversation starters to an appropriate forum channel.
    """

    def __init__(
        self,
        news_config: NewsConfig,
        reflection_api: ReflectionAPI,
        instance: AsyncChatbotInstance,
        channel_selector_agent: ChannelSelectorAgent,
    ):
        self.logger = logging.getLogger(f"{self.__class__.__name__}[{instance.id}]")
        self.news_config = news_config
        self.reflection_api = reflection_api
        self.instance = instance
        self.channel_selector_agent = channel_selector_agent
        self.feed_api = AsyncRSSAPI(self.news_config.feed_url)

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
        interval_seconds = self.news_config.interval_sec
        try:
            while True:
                await asyncio.sleep(interval_seconds)

                # Probability check
                if random.random() >= self.news_config.probability:
                    self.logger.debug("Probability check missed, skipping this cycle.")
                    continue

                await self._execute_news_cycle()

        except asyncio.CancelledError:
            self.logger.info("News background task cancelled during sleep.")
        except Exception:
            self.logger.exception("Unexpected error in news background task.")

    async def _execute_news_cycle(self):
        """Fetch news, generate a message, pick a channel, and send it."""
        # 1. Fetch news
        items = await self.feed_api.fetch(self.news_config.feed_url)
        if not items:
            self.logger.warning("No news items fetched.")
            return

        # Pick the top item (most recent / relevant)
        headline = items[0]
        self.logger.info(f"News cycle triggered with headline: {headline.title}")

        # 2. Generate a conversation starter message via the instance's LLM
        prompt = self.system_prompt_template.format(
            persona=self.instance.persona,
            realtime=self.instance.get_realtime_data(),
        ) + (
            "[SYSTEM]\nStart a casual conversation in a channel. (this is seperate from your current conversation) "
            "React to this news headline in a natural, engaging way that would make others want to join the discussion. "
            f"News: {headline.title}\n"
            f"Details: {headline.summary}\n"
            "Output a valid json, with no formatting or markdown, with the following format:\n"
            "```json\n"
            "{\"message\": <your-reaction>}"
            "```"
        )

        message_text = ""
        async for char in self.instance.stream_ask(message="[SYSTEM] Write your message:", temporal=True, system_prompt=prompt):
            message_text += char

        message_text = message_text.strip()
        if not message_text:
            self.logger.warning("Generated empty message, skipping.")
            return
        try:
            message_text = json.loads(message_text)["message"]
        except Exception:
            self.logger.warning("Generated invalid message, skipping.")

        self.logger.info(f"Generated message: {message_text[:100]}...")
        self.instance.save()

        # 3. Select appropriate channel
        channel_id = None
        forum_id = self.instance.forum_id
        if forum_id is None:
            channel_id = self.instance.chat_id
        else:
            channels = await self.reflection_api.fetch_forum_channels(forum_id)
            if not channels:
                self.logger.warning(f"No channels found for forum {forum_id}.")
                return

            # 3-1. Use the channel selector agent to pick the best channel
            self.channel_selector_agent.set_channels(channels)
            selected_id = await self.channel_selector_agent.execute_query(message_text)
            if selected_id is None:
                self.logger.warning("Channel selector agent returned no channel, skipping.")
                return
            else:
                channel_id = int(selected_id)

        # 4. Send the message
        try:
            await self.reflection_api.send_message(chat_id=channel_id, text=message_text)  # pyright: ignore[reportArgumentType]
            self.logger.info(f"Sent proactive news message to channel {channel_id}.")
        except Exception:
            self.logger.exception(f"Failed to send message to channel {channel_id}.")
