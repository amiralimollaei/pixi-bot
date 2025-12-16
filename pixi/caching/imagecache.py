import os
import tempfile
from typing import Optional

import av

from ..utils import PixiPaths
from .base import MediaCache, CompressedMedia


# constants

THUMBNAIL_SIZE = 512


class ImageCache(MediaCache):
    def __init__(self, data_bytes: Optional[bytes] = None, hash_value: Optional[str] = None):
        super().__init__(
            str(PixiPaths.cache() / "images"),
            format="jpg",
            mime_type="image/jpeg",
            data_bytes=data_bytes,
            hash_value=hash_value
        )

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        with tempfile.NamedTemporaryFile() as tmp_in, tempfile.NamedTemporaryFile(suffix=f".{self.format}") as tmp_out:
            tmp_in.write(data_bytes)
            tmp_in.flush()

            input_file = av.open(tmp_in.name)

            input_stream = input_file.streams.video[0]
            frame = next(input_file.decode(input_stream))
            input_file.close()

            # calculate thumbnail size
            iw, ih = frame.width, frame.height
            scale = min(THUMBNAIL_SIZE / iw, THUMBNAIL_SIZE / ih, 1.0)  # don't upscale

            frame.reformat(width=int(iw * scale), height=int(ih * scale), format='yuvj420p').save(tmp_out.name)

            tmp_out.seek(0)
            audio_bytes = tmp_out.read()

        return CompressedMedia(
            mime_type=self.mime_type,
            bytes=audio_bytes,
            format=self.format
        )
