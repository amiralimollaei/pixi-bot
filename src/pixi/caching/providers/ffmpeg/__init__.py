import errno
import shutil

from ... import DiskMediaCachingProvider, DiskMediaCacheSystem, InMemoryMedia
from .audiocache import AudioCache
from .imagecache import ImageCache

if shutil.which("ffmpeg") is None:
    raise FileNotFoundError(
        errno.ENOENT, "FFmpeg executable was not found on PATH", "ffmpeg"
    )

class FFmpegProvider(DiskMediaCachingProvider):
    """Cache media in short-lived FFmpeg processes without importing PyAV."""

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