import av
import av.logging

av.logging.set_level(av.logging.VERBOSE)

from ... import DiskMediaCachingProvider, InMemoryMedia
from .audiocache import AudioCache
from .imagecache import ImageCache


class PyAVProvider(DiskMediaCachingProvider):
    @staticmethod
    def cache_image(
        data_bytes: bytes | None = None, 
        hash_value: bytes | None = None,
        **metadata
    ) -> bytes:
        return ImageCache.compute_if_absent(data_bytes, hash_value, **metadata)

    @staticmethod
    def cache_audio(
        data_bytes: bytes | None = None, 
        hash_value: bytes | None = None,
        **metadata
    ) -> bytes:
        return AudioCache.compute_if_absent(data_bytes, hash_value, **metadata)
