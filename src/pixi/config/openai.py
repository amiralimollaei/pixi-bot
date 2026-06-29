import dataclasses

@dataclasses.dataclass(frozen=True)
class OpenAIAuthConfig:
    base_url: str
    api_key: str

@dataclasses.dataclass(frozen=True)
class OpenAILanguageModelConfig:
    id: str
    max_context: int
    
@dataclasses.dataclass(frozen=True)
class OpenAIEmbeddingModelConfig:
    id: str
    max_context: int
    dimension: int
    min_chunk_size: int
    max_chunk_size: int
    