import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ...async_utils import AsyncStream
from ...model.openai import ChatCompletionChunk, EmbeddingResponse, ModelList
from .transport import create_embeddings, list_models, stream_chat_completions


class ChatCompletions:
    def __init__(self, client: "AsyncOpenAI"):
        self._client = client

    async def create(self, **kwargs: Any) -> AsyncStream[ChatCompletionChunk]:
        if not kwargs.get("stream", False):
            raise NotImplementedError("Non-streaming chat completions not implemented")
        return AsyncStream(stream_chat_completions(
            base_url=self._client.base_url, api_key=self._client.api_key, payload=kwargs,
        ))


class Chat:
    def __init__(self, client: "AsyncOpenAI"):
        self.completions = ChatCompletions(client)


class Embeddings:
    def __init__(self, client: "AsyncOpenAI"):
        self._client = client

    async def create(self, **kwargs: Any) -> EmbeddingResponse:
        return await create_embeddings(
            base_url=self._client.base_url, api_key=self._client.api_key, payload=kwargs,
        )


class AsyncOpenAI:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.chat = Chat(self)
        self.embeddings = Embeddings(self)


class Models:
    def __init__(self, client: "OpenAI"):
        self._client = client

    def list(self) -> ModelList:
        async def fetch() -> ModelList:
            return await list_models(self._client.base_url, self._client.api_key)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(asyncio.run, fetch()).result()
            return loop.run_until_complete(fetch())
        except RuntimeError:
            return asyncio.run(fetch())


class OpenAI:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.models = Models(self)
