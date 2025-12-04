import logging

from .base import UnsupportedMediaException, MediaCache

logger = logging.getLogger("pixi.caching")

SUPPORTS_MEDIA_CACHING = False
try:
    import av
    import av.logging
    av.logging.set_level(av.logging.VERBOSE)
    SUPPORTS_MEDIA_CACHING = True
except ImportError:
    logger.warning("please install `av` to use media caching features")
else:
    from .audiocache import AudioCache
    from .imagecache import ImageCache

try:
    from .embedding import EmbedingCache
except ImportError:
    logger.warning("please install `numpy` to use embedding vector caching features")
