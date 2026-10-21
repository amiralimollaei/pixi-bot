import subprocess

from ....storage.paths import PixiPaths
from ... import CompressedMedia, DiskMediaCache

THUMBNAIL_SIZE = 512


class ImageCache(DiskMediaCache):
    def __init__(self, data_bytes: bytes | None = None, hash_value: str | None = None):
        super().__init__(
            str(PixiPaths.cache() / "images"),
            format="jpg",
            mime_type="image/jpeg",
            data_bytes=data_bytes,
            hash_value=hash_value,
        )

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-threads", "1", "-filter_threads", "1",
                "-i", "pipe:0", "-map", "0:v:0", "-frames:v", "1",
                "-vf", (
                    f"scale=w='min({THUMBNAIL_SIZE},iw)':"
                    f"h='min({THUMBNAIL_SIZE},ih)':"
                    "force_original_aspect_ratio=decrease"
                ),
                "-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-threads", "1",
                "-f", "image2pipe", "pipe:1",
            ],
            input=data_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return CompressedMedia(
            mime_type=self.mime_type,
            bytes=result.stdout,
            format=self.format,
        )
