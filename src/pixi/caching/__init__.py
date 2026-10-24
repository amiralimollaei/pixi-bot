from __future__ import annotations

import hashlib
import json
import struct
from abc import ABC, abstractmethod
from base64 import b64encode
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Optional, Protocol, Self, TypeVar

from ..interfaces.caching import CacheStorage

if TYPE_CHECKING:
    from ..interfaces.models import EmbeddingModel
    from .embedding import EmbeddingCache


class UnsupportedMediaException(Exception):
    """The requested media is unavailable or has an unsupported format."""


@dataclass(frozen=True)
class InMemoryCache:
    buffer: bytes

    # extra metadata such as the files original extension, duration, etc. can be stored here for later use
    metadata: Optional[dict] = None

    def to_bytes(self) -> bytes:
        metadata_bytes = (
            json.dumps(self.metadata, ensure_ascii=False).encode("utf-8")
            if self.metadata is not None
            else b""
        )
        return b"".join((
            struct.pack(">I", len(self.buffer)),
            self.buffer,
            struct.pack(">I", len(metadata_bytes)),
            metadata_bytes,
        ))

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        offset = 0

        def read_field() -> bytes:
            nonlocal offset

            if len(data) - offset < 4:
                raise ValueError("Truncated length prefix")

            length = struct.unpack_from(">I", data, offset)[0]
            offset += 4

            end = offset + length
            if end > len(data):
                raise ValueError("Truncated field data")

            field = data[offset:end]
            offset = end
            return field

        buffer = read_field()
        metadata_bytes = read_field()

        if offset != len(data):
            raise ValueError("Unexpected trailing bytes")

        metadata = (
            json.loads(metadata_bytes.decode("utf-8"))
            if metadata_bytes
            else None
        )

        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("Metadata must be a JSON object or null")

        return cls(
            buffer=buffer,
            metadata=metadata,
        )

    def to_base64(self):
        return b64encode(self.buffer).decode("utf-8")

    def to_data_url(self) -> str:
        mime_type = (self.metadata or {}).get("mime_type")
        if not isinstance(mime_type, str) or not mime_type:
            raise ValueError("Cache metadata must contain a MIME type to create a data URL.")
        return f"data:{mime_type};base64,{self.to_base64()}"


CacheInput = TypeVar("CacheInput", bytes, str, contravariant=True)


class CacheSystem(Protocol[CacheInput]):
    """Compute and persist cache values from a source value."""

    @staticmethod
    def compute_hash(source: CacheInput, /) -> bytes: ...

    def compute_cache(
        self, source: CacheInput, /, **metadata,
    ) -> InMemoryCache | Awaitable[InMemoryCache]: ...

    def compute_if_absent(
        self, source: CacheInput | None = None, /, hash: bytes | None = None, **metadata,
    ) -> bytes | Awaitable[bytes]: ...

    def write(self, cache: InMemoryCache, hash: bytes) -> None: ...

    def exists(self, hash: bytes) -> bool: ...

    def read(self, hash: bytes) -> InMemoryCache | None: ...


class StoredCacheSystem:
    """Bind cache computation to a namespace in an injected storage backend."""

    def __init__(self, storage: CacheStorage, *, namespace: str):
        self.storage = storage
        self.namespace = namespace

    @staticmethod
    def compute_hash(source: bytes | str) -> bytes:
        data = source.encode("utf-8") if isinstance(source, str) else source
        return hashlib.sha256(data).digest()

    def write(self, cache: InMemoryCache, hash: bytes) -> None:
        self.storage.write(cache, hash, namespace=self.namespace)

    def exists(self, hash: bytes) -> bool:
        return self.storage.exists(hash, namespace=self.namespace)

    def read(self, hash: bytes) -> InMemoryCache | None:
        return self.storage.read(hash, namespace=self.namespace)


class MediaCache(StoredCacheSystem, CacheSystem[bytes], ABC):
    """Media conversion layered on the common cache storage contract."""

    @abstractmethod
    def compute_cache(self, data_bytes: bytes, **metadata) -> InMemoryCache:
        """Convert source media into its cached representation."""

    def compute_if_absent(
        self,
        data_bytes: bytes | None = None,
        hash: bytes | None = None,
        **metadata,
    ) -> bytes:
        if hash is None and data_bytes is not None:
            hash = self.compute_hash(data_bytes)
        if hash is not None and self.exists(hash):
            return hash
        assert data_bytes is not None, "data_bytes is None, can't compute cache"
        cache = self.compute_cache(data_bytes, **metadata)
        if hash is None:
            hash = self.compute_hash(data_bytes)
        self.write(cache, hash)
        return hash


class MediaCacheProvider(Protocol):
    """Media operations supplied by the selected codec backend."""

    def cache_image(
        self,
        data_bytes: bytes | None = None,
        hash_value: bytes | None = None,
        **metadata,
    ) -> bytes: ...

    def cache_audio(
        self,
        data_bytes: bytes | None = None,
        hash_value: bytes | None = None,
        **metadata,
    ) -> bytes: ...

    def load_cache(self, hash: bytes) -> InMemoryCache | None: ...


def get_media_cache(*, storage: CacheStorage | None = None) -> MediaCacheProvider:
    if storage is None:
        from ..storage.paths import PixiPaths
        from .disk import CacheDiskStorage
        storage = CacheDiskStorage(PixiPaths.cache())
    try:
        from .providers.media.ffmpeg import FFmpegProvider
        return FFmpegProvider(storage)
    except (ImportError, FileNotFoundError):
        try:
            from .providers.media.pyav import PyAVProvider
            return PyAVProvider(storage)
        except ImportError as error:
            raise RuntimeError(
                "No media cache provider is available; install optional dependencies: pip install pixi-bot[media]"
            ) from error


def get_embedding_cache(
    *,
    embedding_model: EmbeddingModel,
    storage: CacheStorage | None = None,
) -> EmbeddingCache:
    """Cache embeddings from an explicitly owned model."""
    from .embedding import EmbeddingCache

    if storage is None:
        from ..storage.paths import PixiPaths
        from .disk import CacheDiskStorage
        storage = CacheDiskStorage(PixiPaths.cache())

    return EmbeddingCache(storage, embedding_model=embedding_model)