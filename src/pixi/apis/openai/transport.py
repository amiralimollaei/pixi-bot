import json
import logging
from typing import Any, AsyncIterator

from ...model.openai import ChatCompletionChunk, EmbeddingResponse, ModelList
from ..http import get_http_client_provider
from .exceptions import APIConnectionError, APIError, AuthenticationError

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
    base_url: str, api_key: str, payload: dict[str, Any],
) -> AsyncIterator[ChatCompletionChunk]:
    headers = _build_headers(api_key)
    try:
        async with HTTPClient(base_url.rstrip("/")) as session:
            async with session.post("/chat/completions", json=payload, headers=headers) as response:
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
                            if event.get("choices"):
                                yield ChatCompletionChunk.from_dict(event)
                        except json.JSONDecodeError:
                            logging.debug("Failed to parse SSE data: %s", data)
    except ConnectionError as error:
        raise APIConnectionError(f"Connection error: {error}") from error


async def create_embeddings(
    base_url: str, api_key: str, payload: dict[str, Any],
) -> EmbeddingResponse:
    try:
        async with HTTPClient(base_url) as session:
            async with session.post("/embeddings", json=payload, headers=_build_headers(api_key)) as response:
                if response.status != 200:
                    _handle_response_error(response.status, await response.text())
                return EmbeddingResponse.from_dict(await response.json())
    except ConnectionError as error:
        raise APIConnectionError(f"Connection error: {error}") from error


async def list_models(base_url: str, api_key: str) -> ModelList:
    async with HTTPClient(base_url) as session:
        async with session.get("/models", headers=_build_headers(api_key)) as response:
            if response.status != 200:
                _handle_response_error(response.status, await response.text())
            return ModelList.from_dict(await response.json())
