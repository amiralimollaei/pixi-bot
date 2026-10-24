from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

from ...model.chat import ChatMessageMeta, ToolCallMeta

if TYPE_CHECKING:
    from ...bot.conversations import AsyncChatbotInstance
    from ...interfaces.platform import PlatformMessage


@dataclass
class PartialToolCallMeta:
    name: str
    index: int
    id: str
    arguments: Optional[str] = None

    def to_tool_call(self) -> ToolCallMeta:
        return ToolCallMeta(
            name=self.name,
            index=self.index,
            id=self.id,
            arguments=json.loads(self.arguments) if self.arguments else {}
        )


@dataclass
class ToolContext:
    reference_message: Optional[ChatMessageMeta] = None
    parent_instance: Optional[AsyncChatbotInstance] = None
    platform_message: PlatformMessage | None = None


@dataclass
class ActionContext:
    reference_message: Optional[ChatMessageMeta] = None
    parent_instance: Optional[AsyncChatbotInstance] = None
    platform_message: PlatformMessage | None = None


Predicate = Callable[..., bool]


class AsyncAction(Protocol):
    """An inline action. Implementations may conform without inheriting."""

    @property
    def name(self) -> str: ...

    @property
    def field_name(self) -> str: ...

    @property
    def description(self) -> str | None: ...

    @property
    def is_visible(self) -> bool: ...

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None: ...

    @classmethod
    def should_register(cls, instance: "AsyncChatbotInstance") -> bool:
        """Whether this action is available in the given chat."""
        return True


class AsyncTool(Protocol):
    """An asynchronous tool with an OpenAI-compatible parameters schema."""

    @property
    def name(self) -> str: ...

    @property
    def parameters(self) -> dict | None: ...

    @property
    def description(self) -> str | None: ...

    @classmethod
    async def call(cls, context: ToolContext, *args: Any, **kwargs: Any) -> Any: ...

    @classmethod
    def should_register(cls, instance: "AsyncChatbotInstance") -> bool:
        """Whether this tool is available in the given chat."""
        return True
