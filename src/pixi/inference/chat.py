from typing import AsyncGenerator

from ..apis.openai.adapter import OpenAIChatModel
from ..apis.openai.messages import MediaReader
from ..interfaces.models import ChatEvent, ToolDefinition
from ..model.chat import ChatMessageMeta
from ..model.config.llama import LlamaLanguageModelConfig
from ..model.config.openai import OpenAIAuthConfig
from .server import LlamaServer


class LlamaChatModel(LlamaServer[OpenAIChatModel]):
    """Lazily manages a native llama-server for OpenAI-compatible chat."""

    def __init__(self, config: LlamaLanguageModelConfig, media_cache: MediaReader | None = None):
        super().__init__(config)
        self.model = config
        self.media_cache = media_cache

    async def stream(
        self,
        messages: list[ChatMessageMeta],
        *,
        tools: list[ToolDefinition],
        timestamps: bool = True,
    ) -> AsyncGenerator[ChatEvent, None]:
        async with self._request("Llama chat model is closed") as client:
            stream = client.stream(messages, tools=tools, timestamps=timestamps)
            try:
                async for event in stream:
                    yield event
            finally:
                await stream.aclose()

    def _server_arguments(self) -> tuple[str, ...]:
        return ("--jinja",)

    def _create_client(self, port: int) -> OpenAIChatModel:
        auth = OpenAIAuthConfig(base_url=f"http://127.0.0.1:{port}/v1", api_key="NO_AUTH")
        return OpenAIChatModel(auth, self.model, media_cache=self.media_cache)
