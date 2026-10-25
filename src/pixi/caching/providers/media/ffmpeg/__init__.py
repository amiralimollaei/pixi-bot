import errno
import shutil

from pixi.caching import InMemoryCache, MediaCacheProvider
from pixi.caching.providers.media.ffmpeg.audiocache import AudioCache
from pixi.caching.providers.media.ffmpeg.imagecache import ImageCache
from pixi.interfaces.caching import CacheStorage

if shutil.which("ffmpeg") is None:
    raise FileNotFoundError(
        errno.ENOENT, "FFmpeg executable was not found on PATH", "ffmpeg"
    )


class FFmpegProvider(MediaCacheProvider):
    """Cache media in short-lived FFmpeg processes without importing PyAV."""

    def __init__(self, storage: CacheStorage):
        self.image_cache = ImageCache(storage, namespace="media/v2")
        self.audio_cache = AudioCache(storage, namespace="media/v2")

    def cache_image(
        self,
        data_bytes: bytes | None = None,
        hash_value: bytes | None = None,
        **metadata,
    ) -> bytes:
        return self.image_cache.compute_if_absent(data_bytes, hash_value, **metadata)

    def cache_audio(
        self,
        data_bytes: bytes | None = None,
        hash_value: bytes | None = None,
        **metadata,
    ) -> bytes:
        return self.audio_cache.compute_if_absent(data_bytes, hash_value, **metadata)

    def load_cache(self, hash: bytes) -> InMemoryCache | None:
        return self.image_cache.read(hash)
