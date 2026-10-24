from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass(frozen=True)
class Function:
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str | None = None
    index: int | None = None
    function: Function | None = None
    type: str = "function"


@dataclass(frozen=True)
class ChoiceDelta:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None


@dataclass(frozen=True)
class Choice:
    delta: ChoiceDelta
    finish_reason: str | None = None


@dataclass(frozen=True)
class ChatCompletionChunk:
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[Choice] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatCompletionChunk":
        choices = []
        for item in data.get("choices", [])[:1]:
            delta = item.get("delta", {})
            tool_calls = None
            if "tool_calls" in delta:
                tool_calls = []
                for call in delta["tool_calls"]:
                    function = call.get("function") or {}
                    tool_calls.append(ToolCall(
                        id=call.get("id"), index=call.get("index"),
                        function=Function(name=function.get("name"), arguments=function.get("arguments")),
                        type=call.get("type", "function"),
                    ))
            choices.append(Choice(
                delta=ChoiceDelta(
                    content=delta.get("content"), tool_calls=tool_calls,
                    reasoning_content=delta.get("reasoning_content"),
                ),
                finish_reason=item.get("finish_reason"),
            ))
        return cls(
            id=data.get("id", ""), object=data.get("object", "chat.completion.chunk"),
            created=data.get("created", 0), model=data.get("model", ""), choices=choices,
        )


@dataclass(frozen=True)
class EmbeddingData:
    embedding: list[float]


@dataclass(frozen=True)
class EmbeddingResponse:
    data: list[EmbeddingData]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingResponse":
        return cls([EmbeddingData(embedding=item.get("embedding", [])) for item in data.get("data", [])])


@dataclass(frozen=True)
class ModelInfo:
    id: str


@dataclass(frozen=True)
class ModelList:
    data: list[ModelInfo]

    def __iter__(self) -> Iterator[ModelInfo]:
        return iter(self.data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelList":
        return cls([ModelInfo(id=item.get("id", "")) for item in data.get("data", [])])
