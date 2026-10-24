from pixi.apis.openai.adapter import OpenAIEmbeddingModel
from pixi.model.config.llama import LlamaEmbeddingModelConfig
from pixi.model.config.openai import OpenAIAuthConfig
from pixi.model.embedding import Embedding

from .server import LlamaServer


class LlamaEmbeddingModel(LlamaServer[OpenAIEmbeddingModel]):
    """Lazily manages a native llama-server for OpenAI-compatible embeddings."""

    def __init__(self, model: LlamaEmbeddingModelConfig):
        super().__init__(model)
        self.model = model
        self.cache_identity = (
            "llamacpp", model.hf_repo, model.hf_file or "", str(model.max_context),
        )

    async def embed(self, texts: list[str]) -> list[Embedding]:
        async with self._request("Llama embedding model is closed") as client:
            return await client.embed(texts)

    def _server_arguments(self) -> tuple[str, ...]:
        return ("--embedding",)

    def _binary_help(self) -> str:
        return "Install llama.cpp and, if needed, set --llama-embedding-binary."

    def _create_client(self, port: int) -> OpenAIEmbeddingModel:
        auth = OpenAIAuthConfig(base_url=f"http://127.0.0.1:{port}/v1", api_key="NO_AUTH")
        return OpenAIEmbeddingModel(auth, self.model)
