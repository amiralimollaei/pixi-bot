import errno
import shutil

from pixi.caching import MediaCachePair
from pixi.caching.providers.media.ffmpeg.audiocache import AudioCache
from pixi.caching.providers.media.ffmpeg.imagecache import ImageCache
from pixi.interfaces.caching import CacheStorage

if shutil.which("ffmpeg") is None:
    raise FileNotFoundError(
        errno.ENOENT, "FFmpeg executable was not found on PATH", "ffmpeg"
    )


class FFmpegProvider(MediaCachePair):
    """Cache media in short-lived FFmpeg processes without importing PyAV."""

    def __init__(self, storage: CacheStorage):
        super().__init__(
            ImageCache(storage, namespace="media/v2"),
            AudioCache(storage, namespace="media/v2"),
        )
