import subprocess
import tempfile

from .... import InMemoryCache, MediaCache

CACHE_SAMPLERATE = 16000
CACHE_BITRATE = 32000
CACHE_MAX_DURATION = 30


class AudioCache(MediaCache):

    def compute_cache(self, data_bytes: bytes, **metadata) -> InMemoryCache:
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
        return InMemoryCache(
            buffer=result.stdout,
            metadata={
                **metadata,
                "mime_type": "audio/aac",
                "duration": CACHE_MAX_DURATION,
                "is_cut_off": exceeds_max_duration,
            },
        )
