from enum import StrEnum

from .messages import Messages


class Platform(StrEnum):
    DISCORD = "discord"
    TELEGRAM = "telegram"


class ChatRole(StrEnum):
    SYSTEM: str = "system"
    ASSISTANT: str = "assistant"
    USER: str = "user"
    TOOL: str = "tool"
