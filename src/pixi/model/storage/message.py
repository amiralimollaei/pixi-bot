import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ...caching.base import MediaCache
from ...reflection.message import AbstractMessage
from ...utils import clean_dict
from ..enums import ChatRole


@dataclass(frozen=True)
class FunctionCall:
    name: str
    index: int
    id: str
    arguments: Optional[dict] = None

    def to_dict(self) -> dict:
        return dict(
            name=self.name,
            arguments=self.arguments,
            index=self.index,
            id=self.id
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'FunctionCall':
        return cls(
            name=data["name"],
            index=data["index"],
            id=data["id"],
            arguments=data.get("arguments", {}),
        )


@dataclass
class ChatMessageMeta:
    role: ChatRole | str
    content: Optional[str] = None
    images: list[MediaCache] = field(default_factory=list)
    audio: list[MediaCache] = field(default_factory=list)
    tool_calls: Sequence[FunctionCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None

    # --- additional states---
    metadata: Optional[dict] = None
    message_time: Optional[float] = None

    # --- references ---
    instance_id: Optional[str] = None

    # the original message that this message is instantiated from, should be of type
    # discord.Message or telegram.Message, but the type is not specified here to avoid import
    # errors if one library is not found, is used mostly to reply to the original message
    origin: Optional[AbstractMessage] = None

    bot: Any = None

    def __post_init__(self):
        self.time = (self.message_time if self.message_time and self.message_time > 0 else time.time())

    def to_dict(self) -> dict:
        return clean_dict(dict(
            role=self.role,
            content=self.content,
            metadata=self.metadata,
            time=self.time,
            images=[x.to_dict() for x in self.images or []],
            audio=[x.to_dict() for x in self.audio or []],
            tool_calls=[x.to_dict() for x in self.tool_calls or []],
            tool_call_id=self.tool_call_id
        ))

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatMessageMeta':
        images = []
        if images_cache := data.get("images", []):
            from ...caching import ImageCache
            images = [ImageCache.from_dict(d) for d in images_cache]
        audio = []
        if audio_cache := data.get("audio", []):
            from ...caching import AudioCache
            audio = [AudioCache.from_dict(d) for d in audio_cache]
        return cls(
            role=ChatRole[data["role"].upper()],
            content=data.get("content"),
            metadata=data.get("metadata"),
            message_time=data.get("time", time.time()),
            images=images,  # pyright: ignore[reportArgumentType]
            audio=audio,  # pyright: ignore[reportArgumentType]
            tool_calls=[FunctionCall.from_dict(d) for d in data.get("tool_calls", [])],
            tool_call_id=data.get("tool_call_id")
        )
