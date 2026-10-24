from dataclasses import dataclass


@dataclass(frozen=True)
class LlamaServerConfig:
    hf_repo: str
    hf_file: str | None = None
    binary: str = "llama-server"
    max_context: int = 0
    idle_timeout: float = 60.0
    startup_timeout: float = 600.0


@dataclass(frozen=True)
class LlamaEmbeddingModelConfig(LlamaServerConfig):
    min_chunk_size: int = 256
    max_chunk_size: int = 1024


@dataclass(frozen=True)
class LlamaLanguageModelConfig(LlamaServerConfig):
    max_context: int = 16192

    def __post_init__(self) -> None:
        if self.max_context <= 0:
            raise ValueError("Llama chat model max_context must be positive")

    @property
    def id(self) -> str:
        return self.hf_repo
