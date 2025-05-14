import io
import os
from typing import Optional

# Use ffmpegio to transcode to AAC at the target sample rate
import ffmpegio
# ffmpegio does not support direct BytesIO, so we need to use temp files
import tempfile

from .base import MediaCache, CompressedMedia, UnsupportedMediaException

# constants

CACHE_DIR = os.path.join(".cache", "audio")
CACHE_SAMPLE_RATE = 16000
CACHE_KBIT_RATE = 32
CACHE_MAX_DURATION = 30

# helpers

def get_audio_duration(filepath: str) -> float:
    """Get duration of audio file using ffmpegio."""
    import ffmpegio
    info = ffmpegio.probe.full_details(filepath, select_streams='a')
    # info['streams'] is a list of audio streams; take the first one
    duration = float(info['streams'][0]['duration'])
    return duration

class AudioCache(MediaCache):
    def __init__(self, data_bytes: Optional[bytes] = None, hash_value: Optional[str] = None, strict: bool = False):
        self.strict = strict
        super().__init__(
            CACHE_DIR,
            format="aac",
            mime_type="audio/aac",
            data_bytes=data_bytes,
            hash_value=hash_value
        )

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        # ...existing code...
        with tempfile.NamedTemporaryFile() as tmp_in, tempfile.NamedTemporaryFile(suffix=f".{self.format}") as tmp_out:
            tmp_in.write(data_bytes)
            tmp_in.flush()

            # Use ffprobe to get duration
            duration = get_audio_duration(tmp_in.name)
            rate_in, data = ffmpegio.audio.read(tmp_in.name)
            is_cut_off = False
            if self.strict and duration > CACHE_MAX_DURATION:
                raise UnsupportedMediaException(f"Unsupported media type or format: audio should not be longer than {CACHE_MAX_DURATION} secounds.")
            else:
                data = data[:int(CACHE_MAX_DURATION * rate_in)]
                is_cut_off = True
            ffmpegio.audio.write(
                tmp_out.name,
                rate_in,
                data,
                overwrite=True,
                ar=CACHE_SAMPLE_RATE,
                ac=1,
                map="0:a:0",
                format=self.format,
                **{"b:a": f"{CACHE_KBIT_RATE}k"}
            )
            tmp_out.seek(0)
            audio_bytes = tmp_out.read()

        return CompressedMedia(
            mime_type=self.mime_type,
            bytes=audio_bytes,
            format=self.format,
            metadata=dict(duration=duration, is_cut_off=is_cut_off)
        )