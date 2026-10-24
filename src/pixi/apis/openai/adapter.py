from __future__ import annotations

import array
from typing import Any, AsyncGenerator

from ...model.chat import ChatMessageMeta
from ...model.config.llama import LlamaEmbeddingModelConfig, LlamaLanguageModelConfig
from ...model.config.openai import (OpenAIAuthConfig, OpenAIEmbeddingModelConfig,
                                    OpenAILanguageModelConfig)
from ...model.embedding import Embedding
from ...interfaces.models import (ChatEvent, ChatFinished, ContentDelta,
                             ReasoningDelta, ToolCallDelta, ToolDefinition)
from .client import AsyncOpenAI
from .messages import MediaReader, serialize_message


class OpenAIChatModel:
    def __init__(
        self,
        auth: OpenAIAuthConfig,
        model: OpenAILanguageModelConfig | LlamaLanguageModelConfig,
        media_cache: MediaReader | None = None,
    ):
        self.model = model
        self.media_cache = media_cache
        self.client = AsyncOpenAI(api_key=auth.api_key, base_url=auth.base_url)

    async def stream(
        self,
        messages: list[ChatMessageMeta],
        *,
        tools: list[ToolDefinition],
        timestamps: bool = True,
    ) -> AsyncGenerator[ChatEvent, None]:
        payload = dict(
            model=self.model.id,
            messages=[serialize_message(message, timestamps=timestamps, media_cache=self.media_cache)
                      for message in messages],
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            parallel_tool_calls=True,
            reasoning_effort="high",
            stream=True,
        )
        if tools:
            payload["tools"] = [
                dict(type="function", function=dict(
                    name=tool.name,
                    description=tool.description or tool.name,
                    parameters=tool.parameters or {},
                ))
                for tool in tools
            ]
        stream = await self.client.chat.completions.create(**payload)
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta.content:
                    yield ContentDelta(delta.content)
                if delta.reasoning_content:
                    yield ReasoningDelta(delta.reasoning_content)
                for call in delta.tool_calls or []:
                    assert call.index is not None, "Tool call index is missing"
                    function = call.function
                    yield ToolCallDelta(
                        index=call.index,
                        id=call.id,
                        name=function.name if function else None,
                        arguments=function.arguments if function else None,
                    )
                if choice.finish_reason:
                    yield ChatFinished(choice.finish_reason)
        finally:
            await stream.aclose()


class OpenAIEmbeddingModel:
    def __init__(self, auth: OpenAIAuthConfig, model: OpenAIEmbeddingModelConfig | LlamaEmbeddingModelConfig):
        self.model = model
        self.client = AsyncOpenAI(api_key=auth.api_key, base_url=auth.base_url)
        if isinstance(model, OpenAIEmbeddingModelConfig):
            model_identity = (model.id, str(model.dimension))
        else:
            model_identity = (model.hf_repo, model.hf_file or "", str(model.max_context))
        self.cache_identity = ("openai", auth.base_url.rstrip("/"), *model_identity)

    async def embed(self, texts: list[str]) -> list[Embedding]:
        payload: dict[str, Any] = dict(
            input=texts,
            model=self.model.id if isinstance(self.model, OpenAIEmbeddingModelConfig) else self.model.hf_repo,
            encoding_format="float",
        )
        if isinstance(self.model, OpenAIEmbeddingModelConfig):
            payload["dimensions"] = self.model.dimension
        response = await self.client.embeddings.create(**payload)
        return [
            Embedding(text, len(item.embedding), array.array("f", item.embedding))
            for text, item in zip(texts, response.data)
        ]
