from __future__ import annotations

import hashlib
import json

from pixi.caching import CacheSystem, InMemoryCache, StoredCacheSystem
from pixi.interfaces.caching import CacheStorage
from pixi.interfaces.models import EmbeddingModel


class EmbeddingCache(StoredCacheSystem, CacheSystem[str]):
    """Persist text embeddings in a namespace specific to the embedding model."""

    def __init__(self, storage: CacheStorage, *, embedding_model: EmbeddingModel):
        identity = json.dumps(
            embedding_model.cache_identity, ensure_ascii=False
        ).encode("utf-8")
        namespace = hashlib.sha256(identity).hexdigest()
        super().__init__(storage, namespace=f"embeddings/{namespace}")
        self.embedding_model = embedding_model

    async def compute_cache(self, text: str, **metadata) -> InMemoryCache:
        """Compute a text embedding without looking up or persisting a cache entry."""
        embeddings = await self.embedding_model.embed([text])
        return InMemoryCache(
            buffer=embeddings[0].vec.tobytes(),
            metadata=metadata or None,
        )

    async def compute_if_absent(
        self,
        text: str | None = None,
        hash: bytes | None = None,
        **metadata,
    ) -> bytes:
        """Compute and store on a miss, then return the cache key."""
        if hash is None and text is not None:
            hash = self.compute_hash(text)
        if hash is not None and self.exists(hash):
            return hash
        assert text is not None, "text is None, can't compute an embedding"
        cache = await self.compute_cache(text, **metadata)
        if hash is None:
            hash = self.compute_hash(text)
        self.write(cache, hash)
        return hash
