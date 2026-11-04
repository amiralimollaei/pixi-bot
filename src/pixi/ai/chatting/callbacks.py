from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

from pixi.model.chat import ChatMessage, ToolCall

if TYPE_CHECKING:
    from pixi.bot.conversations import AsyncChatbotInstance
    from pixi.interfaces.platform import PlatformMessage


@dataclass
class PartialToolCall:
    name: str
    index: int
    id: str
    arguments: Optional[str] = None

    def to_tool_call(self) -> ToolCall:
        return ToolCall(
            name=self.name,
            index=self.index,
            id=self.id,
            arguments=json.loads(self.arguments) if self.arguments else {},
        )


@dataclass(frozen=True)
class InvocationContext:
    reference_message: Optional[ChatMessage] = None
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

    async def call(self, context: InvocationContext, value: str | None) -> None: ...

    def should_register(self, instance: "AsyncChatbotInstance") -> bool:
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

    async def call(
        self, context: InvocationContext, *args: Any, **kwargs: Any
    ) -> Any: ...

    def should_register(self, instance: "AsyncChatbotInstance") -> bool:
        """Whether this tool is available in the given chat."""
        return True
