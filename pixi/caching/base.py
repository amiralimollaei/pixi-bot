import os
import hashlib
from base64 import b64encode
from dataclasses import dataclass
from typing import Optional

from ..utils import exists


class UnsupportedMediaException(Exception):
    """Exception raised when an unsupported media type or format is encountered."""

    def __init__(self, message="Unsupported media type or format."):
        super().__init__(message)


@dataclass
class CompressedMedia:
    mime_type: str
    bytes: bytes
    format: Optional[str] = None
    metadata: Optional[dict] = None

    def to_base64(self):
        return b64encode(self.bytes).decode("utf-8")

    def to_data_url(self):
        return "data:image/jpeg;base64," + self.to_base64()


class MediaCache:
    """
    Handles efficient caching of media by generating compressed versions and storing them on disk.
    - If initialized with data_bytes, it creates a hash, optimizes the image, and saves it to the cache.
    - If initialized with a hash, it loads the cached media if available.
    Provides methods to retrieve the media as bytes, or a data URL, and to check cache existence.
    """

    def __init__(self, cache_dir: str, format: str, mime_type: str, data_bytes: Optional[bytes] = None, hash_value: Optional[str] = None):
        assert isinstance(cache_dir, str), f"expected `cache_dir` to be of type str but got {cache_dir}."
        assert isinstance(format, str), f"expected `format` to be of type str but got {format}."
        assert isinstance(mime_type, str), f"expected `mime_type` to be of type str but got {mime_type}."
        assert exists(data_bytes) ^ exists(hash_value), "Only `image_bytes` OR `hash_value` must be provided."

        self.cache_dir = cache_dir
        self.hash = None
        self.media = None
        self.format = format
        self.mime_type = mime_type

        if exists(data_bytes):
            assert isinstance(data_bytes, bytes), "image_bytes must be of type bytes."
            self.hash = self.compute_hash(data_bytes)
            if self.exists():
                self.load_cache()
            else:
                self.media = self.compress(data_bytes)

                os.makedirs(self.cache_dir, exist_ok=True)

                path = self.cache_path
                if path and not os.path.isfile(path):
                    with open(path, "wb") as f:
                        f.write(self.media.bytes)

        if exists(hash_value):
            assert isinstance(hash_value, str), "hash_value must be of type str."
            self.hash = hash_value
            self.load_cache()

    @staticmethod
    def compute_hash(data_bytes: bytes) -> str:
        # hash only the first 16 megabytes for performance
        return hashlib.sha256(data_bytes[:2**24]).hexdigest()

    @property
    def cache_path(self) -> Optional[str]:
        if self.hash:
            return os.path.join(self.cache_dir, f"{self.hash}.{self.format}")
        return None

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        raise NotImplementedError()

    @classmethod
    def from_dict(cls, data: dict):
        if not (hash_value := data.get("hash")):
            raise ValueError("Hash value is required to load ImageCache instance.")
        return cls(hash_value=hash_value)  # type: ignore

    def to_dict(self) -> dict:
        return dict(hash=self.hash)

    def exists(self) -> bool:
        path = self.cache_path
        return exists(path) and os.path.isfile(path)  # type: ignore

    def __ensure_initialized(self):
        if self.media is None:
            raise RuntimeError("attemted to access uninitialized cache")

    def load_cache(self):
        if self.media is None:
            path = self.cache_path
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    self.media = CompressedMedia(
                        mime_type=self.mime_type,
                        bytes=f.read(),
                        format=self.format,
                    )
            else:
                raise FileNotFoundError("Media not found in cache.")
        return self.media

    def get_bytes(self) -> Optional[bytes]:
        if self.media is None:
            self.load_cache()
        assert self.media
        return self.media.bytes

    def get_mime_type(self) -> str:
        return self.mime_type

    def get_format(self) -> str:
        return self.format

    def to_data_url(self) -> str:
        self.__ensure_initialized()
        assert self.media
        return self.media.to_data_url()

    def to_base64(self) -> str:
        self.__ensure_initialized()
        assert self.media
        return self.media.to_base64()
