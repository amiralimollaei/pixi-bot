import tempfile

import av

from ... import InMemoryMedia, DiskMediaCacheSystem


# constants

THUMBNAIL_SIZE = 512


class ImageCache(DiskMediaCacheSystem):
    @classmethod
    def compute_cache(cls, data_bytes: bytes, **metadata) -> InMemoryMedia:
        with tempfile.NamedTemporaryFile() as tmp_in, tempfile.TemporaryFile() as tmp_out:
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
            image_bytes = tmp_out.read()

        return InMemoryMedia(
            mime_type="image/jpeg",
            buffer=image_bytes,
            metadata=metadata
        )

print(ImageCache.directory)