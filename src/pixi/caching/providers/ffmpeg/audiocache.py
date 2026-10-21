import subprocess
import tempfile

from ....storage.paths import PixiPaths
from ... import CompressedMedia, DiskMediaCache, UnsupportedMediaException

CACHE_SAMPLERATE = 16000
CACHE_BITRATE = 32000
CACHE_MAX_DURATION = 30


class AudioCache(DiskMediaCache):
    def __init__(self, data_bytes: bytes | None = None,
                 hash_value: str | None = None, strict: bool = False):
        self.strict = strict
        super().__init__(
            str(PixiPaths.cache() / "audio"),
            format="aac",
            mime_type="audio/aac",
            data_bytes=data_bytes,
            hash_value=hash_value,
        )

    def compress(self, data_bytes: bytes) -> CompressedMedia:
        max_samples = CACHE_SAMPLERATE * CACHE_MAX_DURATION
        # Keep decoded PCM out of Python memory. One extra sample detects cutoff.
        with tempfile.NamedTemporaryFile() as source, tempfile.TemporaryFile() as pcm:
            # M4A/MP4 containers may need to seek back after reading their index.
            source.write(data_bytes)
            source.flush()
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-threads", "1", "-filter_threads", "1", "-i", source.name,
                    "-map", "0:a:0", "-af",
                    f"aresample={CACHE_SAMPLERATE},atrim=end_sample={max_samples + 1}",
                    "-ar", str(CACHE_SAMPLERATE), "-ac", "1",
                    "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
                ],
                stdout=pcm,
                stderr=subprocess.PIPE,
                check=True,
            )
            exceeds_max_duration = pcm.tell() > max_samples * 2
            if self.strict and exceeds_max_duration:
                raise UnsupportedMediaException(
                    f"Audio should not be longer than {CACHE_MAX_DURATION} seconds."
                )
            pcm.seek(0)
            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-threads", "1", "-filter_threads", "1",
                    "-f", "s16le", "-ar", str(CACHE_SAMPLERATE), "-ac", "1",
                    "-i", "pipe:0", "-t", str(CACHE_MAX_DURATION),
                    "-c:a", "aac", "-b:a", str(CACHE_BITRATE), "-threads", "1",
                    "-f", "adts", "pipe:1",
                ],
                stdin=pcm,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        return CompressedMedia(
            mime_type=self.mime_type,
            bytes=result.stdout,
            format=self.format,
            metadata=dict(duration=CACHE_MAX_DURATION, is_cut_off=exceeds_max_duration),
        )
