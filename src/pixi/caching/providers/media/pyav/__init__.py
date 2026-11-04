import av
import av.logging

from pixi.interfaces.caching import CacheStorage

av.logging.set_level(av.logging.VERBOSE)

from pixi.caching import MediaCachePair
from pixi.caching.providers.media.pyav.audiocache import AudioCache
from pixi.caching.providers.media.pyav.imagecache import ImageCache


class PyAVProvider(MediaCachePair):
    def __init__(self, storage: CacheStorage):
        super().__init__(
            ImageCache(storage, namespace="media/v2"),
            AudioCache(storage, namespace="media/v2"),
        )
