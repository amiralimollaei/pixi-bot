import logging

from .base import UnsupportedMediaException, MediaCache

try:
    from .audiocache import AudioCache
except ImportError:
    logging.warning("please install `ffmpegio` to use the audio caching features of pixi")
try:
    from .imagecache import ImageCache
except ImportError:
    logging.warning("please install `pillow` to use the image caching features of pixi")
