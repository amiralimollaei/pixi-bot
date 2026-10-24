from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Optional, Protocol, TYPE_CHECKING

from ..model.config.news import NewsConfig
from ..model.enums import ChatRole
from ..model.chat import ChatMessageMeta
from ..interfaces.platform import PlatformProvider

if TYPE_CHECKING:
    from .conversations import AsyncChatbotInstance


class NewsFeed(Protocol):
    async def fetch(self, max_items: int = 10) -> list: ...


class NewsBackgroundTask:
    """Background task that periodically checks news and sends conversation starters."""

    def __init__(
        self,
        news_config: NewsConfig,
        platform_provider: PlatformProvider,
        instance: AsyncChatbotInstance,
        feed_api: NewsFeed,
        system_prompt_template: str,
    ):
        self.logger = logging.getLogger(f"{self.__class__.__name__}[{instance.id}]")
        self.news_config = news_config
        self.platform_provider = platform_provider
        self.instance = instance
        self.feed_api = feed_api
        self.channel_blacklist: list[int] = []
        self.system_prompt_template = system_prompt_template
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if self._task is not None and not self._task.done():
            self.logger.warning("News background task is already running.")
            return
        self._task = asyncio.create_task(self._run(), name=f"news-task-{self.instance.id}")

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            self.logger.info("News background task cancelled.")

    async def aclose(self) -> None:
        """Stop the news loop and wait for any active request to unwind."""
        task = self._task
        self.stop()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self):
        with self.instance.use():
            interval_seconds = self.news_config.interval_sec
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
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
        self.logger.info("News cycle triggered")
        forum_id = self.instance.forum_id
        if forum_id is None:
            self.logger.warning("News cycle cancelled")
            return
        channels = await self.platform_provider.fetch_forum_channels(forum_id)
        if not channels:
            self.logger.warning("No channels found for forum %s.", forum_id)
            return

        headlines = await self.feed_api.fetch(max_items=10)
        if not headlines:
            self.logger.warning("No news headlines fetched.")
            return

        prompt = self.system_prompt_template.format(
            persona=self.instance.persona,
            realtime=self.instance.get_realtime_data(),
        ) + (
            "[SYSTEM] Start a casual conversation in a channel. (this is seperate from your current conversation) "
            "React to one or more of these news headlines in a natural, engaging way that would make others want to join the discussion. "
            "| title | summary |\n"
            "|---|---|\n"
            + "\n".join([f"{headline.title} | {headline.summary}" for headline in headlines]) + "\n\n"
            "[SYSTEM] You must also choose a channel the message will be sent to, choose carefully, make sure the channel ID (number) is valid."
            "Available Channels:\n"
            + "\n".join([" - " + str(channel.id) for channel in channels]) + "\n\n"
            "Output a valid json, with no formatting or markdown, with the following json schema:\n"
            "```json\n"
            "{\"message\": <your-reaction>, \"channel\": <channel-id-number>}"
            "```"
        )

        message_text = ""
        async for char in self.instance.stream_ask(
            message="[SYSTEM] Write your message:", temporal=True, system_prompt=prompt
        ):
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

        self.logger.info("Generated message: %s...", message_text)
        forum_id = self.instance.forum_id
        if forum_id is None:
            channel_id = self.instance.chat_id
        else:
            channel_id = int(response["channel"])
        assert channel_id

        try:
            message_text = response["message"]
            await self.platform_provider.send_message(chat_id=channel_id, text=message_text)
            self.logger.info("Sent proactive news message to channel %s.", channel_id)
            self.instance.add_message(ChatMessageMeta(ChatRole.ASSISTANT, content=f"[send: {message_text}]"))
            await self.instance.cancel_channel_active_tasks(channel_id=str(channel_id))
        except RuntimeError:
            self.channel_blacklist.append(channel_id)
            self.logger.exception("Failed to send message to channel %s, retrying in 10 seconds...", channel_id)
            await asyncio.sleep(10)
            await self._execute_news_cycle()
