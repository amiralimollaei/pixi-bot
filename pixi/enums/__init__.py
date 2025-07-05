from enum import StrEnum

from .messages import Messages


class Platform(StrEnum):
    DISCORD = "discord"
    TELEGRAM = "telegram"


class ChatRole(StrEnum):
    SYSTEM = "system"
    ASSISTANT = "assistant"
    USER = "user"
    TOOL = "tool"
