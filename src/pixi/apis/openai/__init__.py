import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, AsyncIterator, Generic, Optional, TypeVar

from ..http import get_http_client_provider

HTTPClient = get_http_client_provider()  # type: ignore[reportUnknownVariableType]


# ============================================================================
# Exceptions
# ============================================================================

class APIError(Exception):
    def __init__(self, message: str = "", code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(APIError):
    pass


class APIConnectionError(APIError):
    pass


# ============================================================================
# Data Types for Chat Completions
# ============================================================================

@dataclass
class Function:
    name: Optional[str] = None
    arguments: Optional[str] = None


@dataclass
class ToolCall:
    id: Optional[str] = None
    index: Optional[int] = None
    function: Optional[Function] = None
    type: str = "function"


@dataclass
class ChoiceDelta:
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    reasoning_content: Optional[str] = None


@dataclass
class Choice:
    delta: ChoiceDelta
    finish_reason: Optional[str] = None


@dataclass
class ChatCompletionChunk:
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[Choice] = field(default_factory=list)


# ============================================================================
# AsyncStream
# ============================================================================

T = TypeVar("T")


class AsyncStream(AsyncIterator[T], Generic[T]):
    def __init__(self, iterator: AsyncIterator[T]):
        self._iterator = iterator
        self._aiter = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    def __aiter__(self):
        self._aiter = None
        return self

    async def __anext__(self) -> T:
        if self._aiter is None:
            self._aiter = self._iterator.__aiter__()
        return await self._aiter.__anext__()


# ============================================================================
# HTTP Client Helpers
# ============================================================================

def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _handle_response_error(status: int, text: str) -> None:
    if status == 401:
        raise AuthenticationError(f"Authentication failed: {text}", code=str(status))
    if status == 403:
        raise AuthenticationError(f"Permission denied: {text}", code=str(status))
    raise APIError(f"HTTP {status}: {text}", code=str(status))


# ============================================================================
# Internal Implementations
# ============================================================================

async def _stream_chat_completions(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
) -> AsyncIterator[ChatCompletionChunk]:
    headers = _build_headers(api_key)

    try:
        async with HTTPClient(base_url.rstrip('/')) as session:
            async with session.post("/chat/completions", json=payload, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    _handle_response_error(response.status, text)

                buffer = b""
                async for chunk in response.content:
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            data = line[6:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                event = json.loads(data)
                                choices_data = event.get("choices", [])
                                if not choices_data:
                                    continue

                                choice_data = choices_data[0]
                                delta_data = choice_data.get("delta", {})

                                tool_calls = None
                                if "tool_calls" in delta_data:
                                    tool_calls = []
                                    for tc in delta_data["tool_calls"]:
                                        func_data = tc.get("function") or {}
                                        tool_calls.append(
                                            ToolCall(
                                                id=tc.get("id"),
                                                index=tc.get("index"),
                                                function=Function(
                                                    name=func_data.get("name"),
                                                    arguments=func_data.get(
                                                        "arguments"
                                                    ),
                                                ),
                                                type=tc.get("type", "function"),
                                            )
                                        )

                                delta = ChoiceDelta(
                                    content=delta_data.get("content"),
                                    tool_calls=tool_calls,
                                    reasoning_content=delta_data.get(
                                        "reasoning_content"
                                    ),
                                )

                                choice = Choice(
                                    delta=delta,
                                    finish_reason=choice_data.get("finish_reason"),
                                )

                                yield ChatCompletionChunk(
                                    id=event.get("id", ""),
                                    object=event.get(
                                        "object", "chat.completion.chunk"
                                    ),
                                    created=event.get("created", 0),
                                    model=event.get("model", ""),
                                    choices=[choice],
                                )
                            except json.JSONDecodeError:
                                logging.debug(
                                    f"Failed to parse SSE data: {data}"
                                )
                                continue
    except ConnectionError as e:
        raise APIConnectionError(f"Connection error: {e}") from e


@dataclass
class EmbeddingData:
    embedding: list[float]


@dataclass
class EmbeddingResponse:
    data: list[EmbeddingData]


async def _create_embeddings(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
) -> EmbeddingResponse:
    headers = _build_headers(api_key)

    try:
        async with HTTPClient(base_url) as session:
            async with session.post(
                "/embeddings", json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    _handle_response_error(response.status, text)
                data = await response.json()
                return EmbeddingResponse(
                    [
                        EmbeddingData(embedding=item.get("embedding", []))
                        for item in data.get("data", [])
                    ]
                )
    except ConnectionError as e:
        raise APIConnectionError(f"Connection error: {e}") from e


@dataclass
class ModelInfo:
    id: str


class ModelList:
    def __init__(self, data: list[dict[str, Any]]):
        self._models = [
            ModelInfo(id=m.get("id", "")) for m in data
        ]

    def __iter__(self):
        return iter(self._models)


# ============================================================================
# Public API Classes
# ============================================================================

class ChatCompletions:
    def __init__(self, client: "AsyncOpenAI"):
        self._client = client

    async def create(self, **kwargs: Any) -> AsyncStream[ChatCompletionChunk]:
        stream = kwargs.get("stream", False)
        payload = kwargs

        if not stream:
            payload = {**kwargs, "stream": True}

        stream_iter = _stream_chat_completions(
            base_url=self._client.base_url,
            api_key=self._client.api_key,
            payload=payload,
        )

        if stream:
            return AsyncStream(stream_iter)

        buffer = []
        async for chunk in stream_iter:
            buffer.append(chunk)
        raise NotImplementedError(
            "Non-streaming chat completions not implemented"
        )


class Chat:
    def __init__(self, client: "AsyncOpenAI"):
        self.completions = ChatCompletions(client)


class Embeddings:
    def __init__(self, client: "AsyncOpenAI"):
        self._client = client

    async def create(self, **kwargs: Any) -> EmbeddingResponse:
        return await _create_embeddings(
            base_url=self._client.base_url,
            api_key=self._client.api_key,
            payload=kwargs,
        )


class AsyncOpenAI:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        http_client: Any = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client  # Ignored, kept for compatibility

        self.chat = Chat(self)
        self.embeddings = Embeddings(self)

    def _get_url(self, path: str) -> str:
        """Construct URL from base_url and path, avoiding double slashes."""
        base = self.base_url.rstrip("/")
        seg = path.strip("/")
        return f"{base}/{seg}" if seg else base


class Models:
    def __init__(self, client: "OpenAI"):
        self._client = client

    def list(self, **kwargs: Any) -> ModelList:
        headers = _build_headers(self._client.api_key)

        async def _do() -> ModelList:
            async with HTTPClient(self._client.base_url) as session:
                async with session.get("/models", headers=headers) as response:
                    if response.status != 200:
                        text = await response.text()
                        _handle_response_error(response.status, text)
                    data = await response.json()
                    return ModelList(data.get("data", []))

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=1
                ) as executor:
                    return executor.submit(asyncio.run, _do()).result()
            else:
                return loop.run_until_complete(_do())
        except RuntimeError:
            return asyncio.run(_do())


class OpenAI:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        http_client: Any = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.http_client = http_client
        self.models = Models(self)


# ============================================================================
# Submodule Registration for transparent compatibility
# ============================================================================

# TODO: move everything around to seperate modules, we don't have to follow 
# the openai module structuire

_streaming_mod = ModuleType("openai._streaming")
_streaming_mod.AsyncStream = AsyncStream  # pyright: ignore[reportAttributeAccessIssue]

types_mod = ModuleType("openai.types")

chat_mod = ModuleType("openai.types.chat")
chat_completion_chunk_mod = ModuleType(
    "openai.types.chat.chat_completion_chunk"
)
chat_completion_chunk_mod.ChatCompletionChunk = ChatCompletionChunk  # pyright: ignore[reportAttributeAccessIssue]

chat_mod.chat_completion_chunk = chat_completion_chunk_mod  # pyright: ignore[reportAttributeAccessIssue]
types_mod.chat = chat_mod  # pyright: ignore[reportAttributeAccessIssue]

sys.modules["openai._streaming"] = _streaming_mod
sys.modules["openai.types"] = types_mod
sys.modules["openai.types.chat"] = chat_mod
sys.modules["openai.types.chat.chat_completion_chunk"] = chat_completion_chunk_mod
