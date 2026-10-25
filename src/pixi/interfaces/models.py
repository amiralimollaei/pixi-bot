from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncGenerator, Protocol

from pixi.model.chat import ChatMessageMeta
from pixi.model.embedding import Embedding

if TYPE_CHECKING:
    from pixi.caching import InMemoryCache


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str | None = None
    parameters: dict | None = None


@dataclass(frozen=True)
class ContentDelta:
    content: str


@dataclass(frozen=True)
class ReasoningDelta:
    content: str


@dataclass(frozen=True)
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class ChatFinished:
    reason: str | None = None


ChatEvent = ContentDelta | ReasoningDelta | ToolCallDelta | ChatFinished


class ChatModel(Protocol):
    def stream(
        self,
        messages: list[ChatMessageMeta],
        *,
        tools: list[ToolDefinition],
        timestamps: bool = True,
    ) -> AsyncGenerator[ChatEvent, None]: ...


class EmbeddingCache(Protocol):
    async def compute_cache(self, text: str, **metadata) -> InMemoryCache: ...

    async def compute_if_absent(
        self,
        text: str | None = None,
        hash: bytes | None = None,
        **metadata,
    ) -> bytes: ...

    def read(self, hash: bytes) -> InMemoryCache | None: ...


class EmbeddingModel(Protocol):
    @property
    def cache_identity(self) -> tuple[str, ...]:
        """Stable backend, model, and output settings that determine its vectors."""
        ...

    async def embed(self, texts: list[str]) -> list[Embedding]: ...
