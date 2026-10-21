import av
import av.logging

av.logging.set_level(av.logging.VERBOSE)

from ... import CachingProvider
from .audiocache import AudioCache
from .imagecache import ImageCache


class PyAVProvider(CachingProvider):
    def cache_image(self, data_bytes: bytes | None = None,
                    hash_value: str | None = None) -> ImageCache:
        return ImageCache(data_bytes=data_bytes, hash_value=hash_value)

    def cache_audio(self, data_bytes: bytes | None = None,
                    hash_value: str | None = None,
                    strict: bool = False) -> AudioCache:
        return AudioCache(data_bytes=data_bytes, hash_value=hash_value, strict=strict)
