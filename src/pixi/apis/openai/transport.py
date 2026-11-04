import json
import logging
from typing import Any, AsyncGenerator

from pixi.apis.http import get_http_client_provider
from pixi.apis.openai.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
)
from pixi.interfaces.models import (
    ChatEvent,
    ChatFinished,
    ContentDelta,
    ReasoningDelta,
    ToolCallDelta,
)

HTTPClient = get_http_client_provider()


def _build_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _handle_response_error(status: int, text: str) -> None:
    if status == 401:
        raise AuthenticationError(f"Authentication failed: {text}", code=str(status))
    if status == 403:
        raise AuthenticationError(f"Permission denied: {text}", code=str(status))
    raise APIError(f"HTTP {status}: {text}", code=str(status))


async def stream_chat_completions(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
) -> AsyncGenerator[ChatEvent, None]:
    headers = _build_headers(api_key)
    try:
        async with HTTPClient(base_url.rstrip("/")) as session:
            async with session.post(
                "/chat/completions", json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    _handle_response_error(response.status, await response.text())
                buffer = b""
                async for chunk in response.content:
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.decode("utf-8").strip()
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                            choices = event.get("choices")
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            if delta.get("content"):
                                yield ContentDelta(delta["content"])
                            if delta.get("reasoning_content"):
                                yield ReasoningDelta(delta["reasoning_content"])
                            for call in delta.get("tool_calls", []):
                                index = call.get("index")
                                assert index is not None, "Tool call index is missing"
                                function = call.get("function") or {}
                                yield ToolCallDelta(
                                    index=index,
                                    id=call.get("id"),
                                    name=function.get("name"),
                                    arguments=function.get("arguments"),
                                )
                            if choice.get("finish_reason"):
                                yield ChatFinished(choice["finish_reason"])
                        except json.JSONDecodeError:
                            logging.debug("Failed to parse SSE data: %s", data)
    except ConnectionError as error:
        raise APIConnectionError(f"Connection error: {error}") from error


async def create_embeddings(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
) -> list[list[float]]:
    try:
        async with HTTPClient(base_url) as session:
            async with session.post(
                "/embeddings", json=payload, headers=_build_headers(api_key)
            ) as response:
                if response.status != 200:
                    _handle_response_error(response.status, await response.text())
                data = await response.json()
                return [item.get("embedding", []) for item in data.get("data", [])]
    except ConnectionError as error:
        raise APIConnectionError(f"Connection error: {error}") from error


async def list_models(base_url: str, api_key: str) -> list[str]:
    async with HTTPClient(base_url) as session:
        async with session.get("/models", headers=_build_headers(api_key)) as response:
            if response.status != 200:
                _handle_response_error(response.status, await response.text())
            data = await response.json()
            return [item.get("id", "") for item in data.get("data", [])]
