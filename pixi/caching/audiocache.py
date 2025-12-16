import os
import tempfile
from typing import Optional

import av

from ..utils import PixiPaths

from .base import MediaCache, CompressedMedia, UnsupportedMediaException


# constants

CACHE_SAMPLERATE = 16000
CACHE_BITRATE = 32000
CACHE_MAX_DURATION = 30


class AudioCache(MediaCache):
    def __init__(self, data_bytes: Optional[bytes] = None, hash_value: Optional[str] = None, strict: bool = False):
        self.strict = strict
        super().__init__(
            str(PixiPaths.cache() / "audio"),
            format="aac",
            mime_type="audio/aac",
            data_bytes=data_bytes,
            hash_value=hash_value
        )

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        with tempfile.NamedTemporaryFile() as tmp_in, tempfile.NamedTemporaryFile(suffix=f".{self.format}") as tmp_out:
            tmp_in.write(data_bytes)
            tmp_in.flush()

            input_file = av.open(tmp_in.name)

            input_stream = input_file.streams.audio[0]
            duration = float(input_stream.duration or 0)
            exceeds_max_duration = duration > CACHE_MAX_DURATION
            if self.strict and exceeds_max_duration:
                raise UnsupportedMediaException(
                    f"Unsupported media type or format: audio should not be longer than {CACHE_MAX_DURATION} secounds."
                )

            output_file = av.open(
                tmp_out.name,
                mode="w",
            )
            output_stream = output_file.add_stream(
                "aac",
                rate=CACHE_SAMPLERATE,
                bit_rate=CACHE_BITRATE,
                layout='mono'
            )

            duration = 0.0
            for frame in input_file.decode(input_stream):
                duration += (frame.duration or 0.0) / frame.rate
                for packet in output_stream.encode(frame):
                    output_file.mux(packet)
                if duration > CACHE_MAX_DURATION:
                    break

            # Flush the stream
            for packet in output_stream.encode(None):
                output_file.mux(packet)

            input_file.close()
            output_file.close()

            tmp_out.seek(0)
            audio_bytes = tmp_out.read()

        return CompressedMedia(
            mime_type=self.mime_type,
            bytes=audio_bytes,
            format=self.format,
            metadata=dict(duration=CACHE_MAX_DURATION, is_cut_off=exceeds_max_duration)
        )
