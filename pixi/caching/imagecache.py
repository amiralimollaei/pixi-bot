import io
import os
from typing import Optional

import PIL.Image as Image

from .base import MediaCache, CompressedMedia


# constants

CACHE_DIR = os.path.join(".cache", "images")
THUMBNAIL_SIZE = 512
THUMBNAIL_QUALITY = 75


class ImageCache(MediaCache):
    def __init__(self, data_bytes: Optional[bytes] = None, hash_value: Optional[str] = None):
        super().__init__(
            CACHE_DIR,
            format="jpeg",
            mime_type="image/jpeg",
            data_bytes=data_bytes,
            hash_value=hash_value
        )

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        image = Image.open(io.BytesIO(data_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.BILINEAR)
        with io.BytesIO() as output:
            image.save(output, format=self.format, quality=75)
            image_bytes = output.getvalue()
        return CompressedMedia(
            mime_type=self.mime_type,
            bytes=image_bytes,
            format=self.format
        )
