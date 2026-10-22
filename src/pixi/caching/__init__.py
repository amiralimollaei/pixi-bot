import hashlib
import json
import struct
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Self, Tuple


class UnsupportedMediaException(Exception):
    """Exception raised when an unsupported media type or format is encountered."""

    def __init__(self, message="Unsupported media type or format."):
        super().__init__(message)


@dataclass(frozen=True)
class InMemoryMedia:
    mime_type: str
    buffer: bytes

    # extra metadata such as the files original extension, duration, etc. can be stored here for later use
    metadata: Optional[dict] = None

    def to_bytes(self) -> bytes:
        mime_bytes = self.mime_type.encode("utf-8")
        metadata_bytes = (
            json.dumps(self.metadata, ensure_ascii=False).encode("utf-8")
            if self.metadata is not None
            else b""
        )
        return b"".join((
            struct.pack(">I", len(mime_bytes)),
            mime_bytes,
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

        mime_bytes = read_field()
        buffer = read_field()
        metadata_bytes = read_field()

        if offset != len(data):
            raise ValueError("Unexpected trailing bytes")

        mime_type = mime_bytes.decode("utf-8")
        metadata = (
            json.loads(metadata_bytes.decode("utf-8"))
            if metadata_bytes
            else None
        )

        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("Metadata must be a JSON object or null")

        return cls(
            mime_type=mime_type,
            buffer=buffer,
            metadata=metadata,
        )

    def to_base64(self):
        return b64encode(self.buffer).decode("utf-8")

    def to_data_url(self):
        return f"data:{self.mime_type};base64,{self.to_base64()}"


class MediaCacheSystem(Protocol):
    """Protocol class for media caching, interface for caching media files."""

    @classmethod
    def compute_cache(cls, data_bytes: bytes, **metadata) -> InMemoryMedia:
        """Compute the in-memory data to be written in the cache, returning a InMemoryMedia instance."""
        ...

    @staticmethod
    def compute_hash(data_bytes: bytes) -> bytes:
        """Compute the hash of the input, and return it as bytes"""
        return hashlib.sha256(data_bytes).digest()

    @classmethod
    def write(cls, media: InMemoryMedia, hash: bytes):
        """Write the InMemoryMedia to cache, returning the hash in bytes"""
        ...

    @classmethod
    def exists(cls, hash: bytes) -> bool:
        """Checks whether an entry exists in the cache"""
        ...

    @classmethod
    def read(cls, hash: bytes) -> Optional[InMemoryMedia]:
        """Read the media from cache and return a InMemoryMedia instance, or None if not found."""
        ...

    @classmethod
    def compute_if_absent(cls, data_bytes: Optional[bytes], hash: Optional[bytes], **metadata) -> bytes:
        """Read cached data if they exist, or compute the in-memory cache data, and write them to the cache, returning the hash in bytes"""
        if hash is None and data_bytes is not None:
            hash = cls.compute_hash(data_bytes)
        if hash is not None and cls.exists(hash):
            return hash
        else:
            assert data_bytes, "data_bytes is None, can't compute cache"
            media = cls.compute_cache(data_bytes=data_bytes, **metadata)
            if hash is None:
                hash = cls.compute_hash(data_bytes)
            cls.write(media, hash)
            return hash


class DiskMediaCacheSystem(MediaCacheSystem):
    """Shared on-disk implementation for compressed media caches."""

    directory: Path

    @classmethod
    def __save_path(cls, hash: bytes) -> Path:
        return cls.directory / hash.hex()

    @classmethod
    def write(cls, media: InMemoryMedia, hash: bytes):
        path = cls.__save_path(hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(media.to_bytes())
    
    @classmethod
    def exists(cls, hash: bytes) -> bool:
        return cls.__save_path(hash).exists()

    @classmethod
    def read(cls, hash: bytes) -> Optional[InMemoryMedia]:
        if (path := cls.__save_path(hash)).exists():
            return InMemoryMedia.from_bytes(path.read_bytes())


class DiskMediaCachingProvider(Protocol):
    """Media cache construction and restoration, independent of the codec backend.

    Select a concrete provider with get_caching_provider(), then construct it
    without arguments. Cache dictionaries retain only their source-data hash.
    """

    @staticmethod
    def cache_image(
        data_bytes: Optional[bytes] = None,
        hash_value: Optional[bytes] = None,
        **metadata
    ) -> bytes: ...

    @staticmethod
    def cache_audio(
        data_bytes: Optional[bytes] = None,
        hash_value: Optional[bytes] = None,
        **metadata
    ) -> bytes: ...

    @staticmethod
    def load_media(hash: bytes) -> InMemoryMedia | None:
        return DiskMediaCacheSystem.read(hash)


def get_caching_provider() -> type[DiskMediaCachingProvider]:
    try:
        from .providers.ffmpeg import FFmpegProvider
        return FFmpegProvider
    except (ImportError, FileNotFoundError):
        try:
            from .providers.pyav import PyAVProvider
            return PyAVProvider
        except ImportError:
            raise RuntimeError(
                "No caching provider is available; install optional dependencies: pip install pixi-bot[media]"
            )
