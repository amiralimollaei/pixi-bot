from typing import Protocol


class LanguageModelConfig(Protocol):
    """Shared attributes of a chat language model configuration."""

    id: str
    max_context: int
