import logging

import httpx
import numpy as np
import openai

from .embedding import EmbeddingCache
from ..model.config.openai import OpenAIAuthConfig, OpenAIEmbeddingModelConfig
from ..model.search.document import (DocumentReference, TextPieceMatch,
                                     VectorTextPiece)
from .splitter import SmartSplitter


class AsyncRAGClient:
    def __init__(self, auth: OpenAIAuthConfig, model: OpenAIEmbeddingModelConfig):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.auth = auth
        self.model = model

        self.splitter = SmartSplitter(max_size=self.model.max_chunk_size, min_size=self.model.min_chunk_size)

        self.dataset: list[VectorTextPiece] = []

        self.client = openai.AsyncOpenAI(
            base_url=self.auth.base_url,
            api_key=self.auth.api_key,
            # don't use proxies from environment variables
            http_client=httpx.AsyncClient(trust_env=False),
        )

    async def add_document_piece(self, input: str | list[str], reference: DocumentReference):
        embeddings = await self.embed(input)

        if isinstance(embeddings, EmbeddingCache):
            embeddings = [embeddings]

        for embedding in embeddings:
            self.dataset.append(VectorTextPiece(
                data=embedding,
                reference=reference
            ))

    async def add_document(
        self,
        text: str,
        name: str,
        id: int,
    ):
        """
        breaks the document into smaller pieses and adds them using `self.add_document_piece(...)`

        params:
            text: (str) the full text of the document to be porcessed
            name: (str) the name of the document used for referencing
            id: (int) the id of the document used for referencing

        returns:
            None
        """

        await self.add_document_piece(
            input=self.splitter.split(text),
            reference=DocumentReference(
                name=name,
                id=id
            )
        )

    async def embed(self, input: str | list[str]):
        assert self.model.dimension, "no embedding dimension specified"

        was_unbatched = False
        if isinstance(input, str):
            input = [input]
            was_unbatched = True

        missed_inputs = []
        results: list[EmbeddingCache] = []
        for input_text in input:
            try:
                results.append(EmbeddingCache(text=input_text, dim=self.model.dimension))
            except FileNotFoundError:
                # cache miss
                missed_inputs.append(input_text)
                continue
            except Exception:
                self.logger.exception("Error loading embedding cache")
                # cache error
                missed_inputs.append(input_text)
                continue

        if missed_inputs:
            assert self.model, "no embedding model specified"

            embedding_response = await self.client.embeddings.create(
                input=missed_inputs,
                model=self.model.id,
                dimensions=self.model.dimension,
                encoding_format="float"
            )

            for embedding_data, embedding_text in zip(embedding_response.data, missed_inputs):
                results.append(EmbeddingCache(
                    text=embedding_text,
                    dim=self.model.dimension,
                    vec=np.array(embedding_data.embedding, dtype="float16"),
                ))

        return results[0] if was_unbatched else results

    def similarity(
        self,
        query: EmbeddingCache,
        document: VectorTextPiece,
        epsilon: float = 1e-6,
    ) -> float:
        assert epsilon != 0.0
        assert query.vec is not None
        assert document.vec is not None

        q_dot_docs = (query.vec * document.vec).sum(axis=-1)
        norm_coeff = np.linalg.norm(query.vec, axis=-1) * np.linalg.norm(document.vec, axis=-1)
        norm_coeff = np.clip(norm_coeff, a_min=epsilon, a_max=None)  # avoid devision by zero

        return float(q_dot_docs / norm_coeff)

    def search(self, query: EmbeddingCache, best_n: int = 10):
        matches: list[TextPieceMatch] = []
        for document_piece in self.dataset:
            similarity_score = self.similarity(query, document_piece)
            matches.append(TextPieceMatch(
                text=document_piece.text,
                similarity_score=similarity_score,
                reference=document_piece.reference
            ))
        return sorted(matches, key=lambda x: x.similarity_score, reverse=True)[:best_n]
