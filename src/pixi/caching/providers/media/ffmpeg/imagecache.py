import subprocess

from .... import InMemoryCache, MediaCache

THUMBNAIL_SIZE = 512


class ImageCache(MediaCache):
    
    def compute_cache(self, data_bytes: bytes, **metadata) -> InMemoryCache:
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
        return InMemoryCache(
            buffer=result.stdout,
            metadata={**metadata, "mime_type": "image/jpeg"},
        )
