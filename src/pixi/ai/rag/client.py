import array
import logging
import math
from typing import overload

from pixi.ai.rag.splitter import SmartSplitter
from pixi.interfaces.models import EmbeddingCache
from pixi.model.config.llama import LlamaEmbeddingModelConfig
from pixi.model.config.openai import OpenAIEmbeddingModelConfig
from pixi.model.embedding import Embedding
from pixi.model.search.document import (
    DocumentReference,
    TextPieceMatch,
    VectorTextPiece,
)


class AsyncRAGClient:
    def __init__(
        self,
        *,
        cache: EmbeddingCache,
        model: OpenAIEmbeddingModelConfig | LlamaEmbeddingModelConfig,
    ):
        self.logger = logging.getLogger(type(self).__name__)
        self.cache = cache
        self.model = model
        self.splitter = SmartSplitter(
            max_size=model.max_chunk_size, min_size=model.min_chunk_size
        )
        self.pieces: list[VectorTextPiece] = []

    async def add_document_piece(
        self, input: str | list[str], reference: DocumentReference
    ):
        embeddings = await self.embed(input)
        if isinstance(embeddings, Embedding):
            embeddings = [embeddings]
        for embedding in embeddings:
            self.pieces.append(VectorTextPiece(data=embedding, reference=reference))

    async def add_document(self, text: str, name: str, id: int):
        await self.add_document_piece(
            self.splitter.split(text), DocumentReference(name=name, id=id)
        )

    @overload
    async def embed(self, input: str) -> Embedding: ...

    @overload
    async def embed(self, input: list[str]) -> list[Embedding]: ...

    async def embed(self, input: str | list[str]) -> Embedding | list[Embedding]:
        texts = [input] if isinstance(input, str) else input
        embeddings = []
        for text in texts:
            key = await self.cache.compute_if_absent(text)
            cached = self.cache.read(key)
            if cached is None:
                raise FileNotFoundError(
                    f"Embedding cache entry {key.hex()} is missing."
                )
            vec = array.array("f")
            vec.frombytes(cached.buffer)
            embeddings.append(Embedding(text, len(vec), vec))
        return embeddings[0] if isinstance(input, str) else embeddings

    def similarity(
        self, query: Embedding, document: VectorTextPiece, epsilon: float = 1e-6
    ) -> float:
        assert epsilon != 0.0
        q_dot_docs = sum(q * d for q, d in zip(query.vec, document.vec))
        norm = math.sqrt(sum(value * value for value in query.vec)) * math.sqrt(
            sum(value * value for value in document.vec)
        )
        return q_dot_docs / max(epsilon, norm)

    def search(self, query: Embedding, best_n: int = 10) -> list[TextPieceMatch]:
        matches = [
            TextPieceMatch(
                text=piece.text,
                similarity_score=self.similarity(query, piece),
                reference=piece.reference,
            )
            for piece in self.pieces
        ]
        return sorted(matches, key=lambda match: match.similarity_score, reverse=True)[
            :best_n
        ]
