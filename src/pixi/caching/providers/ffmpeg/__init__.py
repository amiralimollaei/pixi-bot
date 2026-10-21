import errno
import shutil

from ... import CachingProvider
from .audiocache import AudioCache
from .imagecache import ImageCache

if shutil.which("ffmpeg") is None:
    raise FileNotFoundError(
        errno.ENOENT, "FFmpeg executable was not found on PATH", "ffmpeg"
    )

class FFmpegProvider(CachingProvider):
    """Cache media in short-lived FFmpeg processes without importing PyAV."""

    def cache_image(self, data_bytes: bytes | None = None,
                    hash_value: str | None = None) -> ImageCache:
        return ImageCache(data_bytes=data_bytes, hash_value=hash_value)

    def cache_audio(self, data_bytes: bytes | None = None,
                    hash_value: str | None = None,
                    strict: bool = False) -> AudioCache:
        return AudioCache(
            data_bytes=data_bytes, hash_value=hash_value, strict=strict
        )
