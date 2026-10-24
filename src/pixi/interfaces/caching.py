from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..caching import InMemoryCache


class CacheStorage(Protocol):
    """Persist serialized cache values, isolated by namespace and binary key."""

    def write(self, cache: InMemoryCache, hash: bytes, *, namespace: str) -> None:
        """Replace the value for this namespace/key, including its metadata."""
        ...

    def exists(self, hash: bytes, *, namespace: str) -> bool:
        ...

    def read(self, hash: bytes, *, namespace: str) -> InMemoryCache | None:
        """Return None for a missing entry; empty buffers are valid values."""
        ...
