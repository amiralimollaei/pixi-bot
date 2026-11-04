import tempfile

import av

from pixi.caching import InMemoryCache, MediaCache

# constants

CACHE_SAMPLERATE = 16000
CACHE_BITRATE = 32000
CACHE_MAX_DURATION = 30


class AudioCache(MediaCache):
    def compute_cache(self, data_bytes: bytes, **metadata) -> InMemoryCache:
        with (
            tempfile.NamedTemporaryFile() as tmp_in,
            tempfile.NamedTemporaryFile(suffix=".aac") as tmp_out,
        ):
            tmp_in.write(data_bytes)
            tmp_in.flush()

            input_file = av.open(tmp_in.name)

            input_stream = input_file.streams.audio[0]
            duration = float(input_stream.duration or 0)
            exceeds_max_duration = duration > CACHE_MAX_DURATION

            output_file = av.open(
                tmp_out.name,
                mode="w",
                format="adts",
            )
            output_stream = output_file.add_stream(
                "aac", rate=CACHE_SAMPLERATE, bit_rate=CACHE_BITRATE, layout="mono"
            )

            # Create a resampler to convert input audio to the cache format
            resampler = av.AudioResampler(
                format=output_stream.codec_context.format,
                layout=output_stream.codec_context.layout,
                rate=output_stream.codec_context.sample_rate,
            )

            duration = 0.0
            for frame in input_file.decode(input_stream):
                # Resample the frame to match the output stream's format
                resampled_frames = resampler.resample(frame)
                for resampled_frame in resampled_frames:
                    duration += (resampled_frame.duration or 0.0) / resampled_frame.rate
                    for packet in output_stream.encode(resampled_frame):
                        output_file.mux(packet)
                if duration > CACHE_MAX_DURATION:
                    break

            # Flush the resampler (pass None to flush any buffered audio)
            for resampled_frame in resampler.resample(None):
                for packet in output_stream.encode(resampled_frame):
                    output_file.mux(packet)

            # Flush the stream
            for packet in output_stream.encode(None):
                output_file.mux(packet)

            input_file.close()
            output_file.close()

            tmp_out.seek(0)
            audio_bytes = tmp_out.read()

        return InMemoryCache(
            buffer=audio_bytes,
            metadata={
                **metadata,
                "mime_type": "audio/aac",
                "duration": CACHE_MAX_DURATION,
                "is_cut_off": exceeds_max_duration,
            },
        )
