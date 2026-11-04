from __future__ import annotations

import array
from typing import Any, AsyncGenerator

from pixi.apis.openai.messages import MediaReader, serialize_message
from pixi.apis.openai.transport import create_embeddings, stream_chat_completions
from pixi.interfaces.models import (
    ChatEvent,
    ToolDefinition,
)
from pixi.model.chat import ChatMessage
from pixi.model.config.language import LanguageModelConfig
from pixi.model.config.llama import LlamaEmbeddingModelConfig
from pixi.model.config.openai import (
    OpenAIAuthConfig,
    OpenAIEmbeddingModelConfig,
)
from pixi.model.embedding import Embedding


class OpenAIChatModel:
    def __init__(
        self,
        auth: OpenAIAuthConfig,
        model: LanguageModelConfig,
        media_cache: MediaReader | None = None,
    ):
        self.model = model
        self.media_cache = media_cache
        self.base_url = auth.base_url.rstrip("/")
        self.api_key = auth.api_key

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolDefinition],
        timestamps: bool = True,
    ) -> AsyncGenerator[ChatEvent, None]:
        payload = dict(
            model=self.model.id,
            messages=[
                serialize_message(
                    message, timestamps=timestamps, media_cache=self.media_cache
                )
                for message in messages
            ],
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            parallel_tool_calls=True,
            reasoning_effort="high",
            stream=True,
        )
        if tools:
            payload["tools"] = [
                dict(
                    type="function",
                    function=dict(
                        name=tool.name,
                        description=tool.description or tool.name,
                        parameters=tool.parameters or {},
                    ),
                )
                for tool in tools
            ]
        stream = stream_chat_completions(self.base_url, self.api_key, payload)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()


class OpenAIEmbeddingModel:
    def __init__(
        self,
        auth: OpenAIAuthConfig,
        model: OpenAIEmbeddingModelConfig | LlamaEmbeddingModelConfig,
    ):
        self.model = model
        self.base_url = auth.base_url.rstrip("/")
        self.api_key = auth.api_key
        if isinstance(model, OpenAIEmbeddingModelConfig):
            model_identity = (model.id, str(model.dimension))
        else:
            model_identity = (
                model.hf_repo,
                model.hf_file or "",
                str(model.max_context),
            )
        self.cache_identity = ("openai", auth.base_url.rstrip("/"), *model_identity)

    async def embed(self, texts: list[str]) -> list[Embedding]:
        payload: dict[str, Any] = dict(
            input=texts,
            model=self.model.id
            if isinstance(self.model, OpenAIEmbeddingModelConfig)
            else self.model.hf_repo,
            encoding_format="float",
        )
        if isinstance(self.model, OpenAIEmbeddingModelConfig):
            payload["dimensions"] = self.model.dimension
        embeddings = await create_embeddings(self.base_url, self.api_key, payload)
        return [
            Embedding(text, len(embedding), array.array("f", embedding))
            for text, embedding in zip(texts, embeddings)
        ]
