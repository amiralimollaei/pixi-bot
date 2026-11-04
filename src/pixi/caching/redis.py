import hashlib
from typing import cast

from redis.client import Redis
from redis.connection import ConnectionPool

from pixi.caching import InMemoryCache
from pixi.interfaces.caching import CacheStorage


class CacheRedisStorage(CacheStorage):
    """Store serialized cache entries as binary Redis values."""

    def __init__(self, url: str, *, key_prefix: str = "pixi:cache:"):
        # URL options override constructor kwargs; force binary responses after
        # parsing the URL, before any connections or client encoders are created.
        self._pool = ConnectionPool.from_url(url)
        self._pool.connection_kwargs["decode_responses"] = False
        self._client = Redis(connection_pool=self._pool)
        self.key_prefix = key_prefix

    def _key(self, hash: bytes, *, namespace: str) -> str:
        namespace_hash = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        return f"{self.key_prefix}{namespace_hash}:{hash.hex()}"

    def write(self, cache: InMemoryCache, hash: bytes, *, namespace: str) -> None:
        value = cache.to_bytes()
        self._client.set(self._key(hash, namespace=namespace), value)

    def exists(self, hash: bytes, *, namespace: str) -> bool:
        return bool(self._client.exists(self._key(hash, namespace=namespace)))

    def read(self, hash: bytes, *, namespace: str) -> InMemoryCache | None:
        value = self._client.get(self._key(hash, namespace=namespace))
        if value is None:
            return None
        return InMemoryCache.from_bytes(cast(bytes, value))

    def close(self) -> None:
        try:
            self._client.close()
        finally:
            self._pool.disconnect()
