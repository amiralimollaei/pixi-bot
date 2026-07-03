import json
import logging
from typing import Optional

from ..reflection import ChannelMeta
from .base import AgentBase


class ChannelSelectorAgent(AgentBase):
    """
    Selects the most appropriate forum channel for a proactive conversation starter message.
    """

    def __init__(self, *, channels: Optional[list[ChannelMeta]] = None, **client_kwargs):
        super().__init__(**client_kwargs)
        self.logger = logging.getLogger(self.__class__.__name__)

        self.channels = channels or []

        self.system_prompt = "\n".join([
            "## You are a channel selection agent",
            "",
            "You are part of Pixi, an AI chatbot. Given a list of available forum channels",
            "(e.g., Discord text channels within a guild), the Pixi persona's character,",
            "and a proactive message that Pixi wants to send, you must pick the most",
            "appropriate channel to send the message to.",
            "",
            "Rules:",
            "- Choose a channel where the message would be most relevant and engaging.",
            "- If the message is about general news, 'general' or 'chat' channels are good.",
            "- If it's about a specific topic, pick a corresponding channel if one exists.",
            "- If no channel is dedicated to the topic, choose the off-topic channel if one exists, otherwise choose the closest channel."
            "- Return ONLY valid JSON with no extra text or markdown formatting.",
            "",
            "Output format:",
            "{\"channel_id\": 123456789}",
        ])
        self.client.set_system(self.system_prompt)

    def set_channels(self, channels: list[ChannelMeta]):
        """Set the available channels for channel selection."""
        self.channels = channels

    def to_dict(self) -> dict:
        return super().to_dict() | dict(
            channels=[
                {"id": c.id, "name": c.name, "mention": c.mention}
                for c in self.channels
            ]
        )

    @classmethod
    def from_dict(cls, data: dict, **client_kwargs) -> 'ChannelSelectorAgent':
        return cls(
            client=AgentBase.client_from_dict(data, **client_kwargs),
            channels=data.get("channels", []),
        )

    def format_query(self, query: str) -> str:
        channels_str = json.dumps([
            {"id": c.id, "name": c.name, "mention": c.mention}
            for c in self.channels
        ], ensure_ascii=False)

        prompt = "\n".join([
            "Available channels:",
            channels_str,
            "",
            f"Message to send: \"{query}\"",
            "",
            "Which channel_id should this message be sent to? Return ONLY valid JSON.",
        ])
        return prompt

    async def execute_query(self, query: str, temporal=True) -> Optional[str]:
        """
        Execute the channel selection query and return the selected channel ID.

        Returns:
            The selected channel_id as an str, or None if no valid channel was found
        """
        if not self.channels:
            self.logger.warning(
                "No channels available for selection."
            )
            return None

        response = await super().execute_query(query = query, temporal = temporal)
        if not response:
            self.logger.warning(
                "Channel selector agent returned empty response."
            )
            return None

        try:
            # Strip any markdown code block wrapping
            if response.startswith("```"):
                response = response.split("\n", 1)[-1]
                if "```" in response:
                    response = response.rsplit("```", 1)[0]
            data = json.loads(response.strip())
            channel_id = data.get("channel_id")
            if channel_id is not None:
                # Verify the channel_id is actually in the provided list
                valid_ids = {c.id for c in self.channels}
                if int(channel_id) in valid_ids:
                    return channel_id
                else:
                    self.logger.warning(
                        f"Channel selector returned invalid channel_id {channel_id}."
                    )
                    return None
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            self.logger.exception(
                f"Failed to parse channel selector response: {e}\nResponse: {response}"
            )
            return None

        return None
