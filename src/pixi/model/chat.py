import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from pixi.model.enums import ChatRole
from pixi.utils import clean_dict


@dataclass(frozen=True)
class ToolCallMeta:
    name: str
    index: int
    id: str
    arguments: Optional[dict] = None

    def to_dict(self) -> dict:
        return dict(
            name=self.name, arguments=self.arguments, index=self.index, id=self.id
        )

    @classmethod
    def from_dict(cls, data: dict) -> "ToolCallMeta":
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
    image_hashes: list[bytes] = field(default_factory=list)
    audio_hashes: list[bytes] = field(default_factory=list)
    tool_calls: Sequence[ToolCallMeta] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    metadata: Optional[dict] = None
    message_time: Optional[float] = None
    channel_id: int | None = None

    def __post_init__(self):
        self.time = (
            self.message_time
            if self.message_time and self.message_time > 0
            else time.time()
        )

    def to_dict(self) -> dict:
        return clean_dict(
            dict(
                role=self.role,
                content=self.content,
                metadata=self.metadata,
                time=self.time,
                image_hashes=[b.hex() for b in self.image_hashes or []],
                audio_hashes=[b.hex() for b in self.audio_hashes or []],
                tool_calls=[x.to_dict() for x in self.tool_calls or []],
                tool_call_id=self.tool_call_id,
                channel_id=self.channel_id,
            )
        )

    @classmethod
    def from_dict(cls, data: dict) -> "ChatMessageMeta":
        return cls(
            role=ChatRole[data["role"].upper()],
            content=data.get("content"),
            metadata=data.get("metadata"),
            message_time=data.get("time", time.time()),
            image_hashes=[bytes.fromhex(h) for h in data.get("image_hashes", [])],
            audio_hashes=[bytes.fromhex(h) for h in data.get("audio_hashes", [])],
            tool_calls=[ToolCallMeta.from_dict(d) for d in data.get("tool_calls", [])],
            tool_call_id=data.get("tool_call_id"),
            channel_id=data.get("channel_id"),
        )
