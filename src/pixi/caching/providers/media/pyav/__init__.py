from .....interfaces.caching import CacheStorage

import av
import av.logging

av.logging.set_level(av.logging.VERBOSE)

from .... import MediaCacheProvider, InMemoryCache
from .audiocache import AudioCache
from .imagecache import ImageCache


class PyAVProvider(MediaCacheProvider):
    def __init__(self, storage: CacheStorage):
        self.image_cache = ImageCache(storage, namespace="media/v2")
        self.audio_cache = AudioCache(storage, namespace="media/v2")

    def cache_image(
        self,
        data_bytes: bytes | None = None, 
        hash_value: bytes | None = None,
        **metadata
    ) -> bytes:
        return self.image_cache.compute_if_absent(data_bytes, hash_value, **metadata)

    def cache_audio(
        self,
        data_bytes: bytes | None = None, 
        hash_value: bytes | None = None,
        **metadata
    ) -> bytes:
        return self.audio_cache.compute_if_absent(data_bytes, hash_value, **metadata)

    def load_cache(self, hash: bytes) -> InMemoryCache | None:
        return self.image_cache.read(hash)
