from base64 import b64encode
from enum import StrEnum
import io
import logging
import os
import hashlib
from typing import Optional

import PIL.Image as Image


# helpers

def exists(value, allow_empty_string=False):
    if value is None:
        return False

    if isinstance(value, (int, float)):
        return True

    if isinstance(value, str):
        return value != "" or (value == "" and allow_empty_string)

    if isinstance(value, (list, tuple, dict)):
        return len(value) != 0

    return True


def load_dotenv():
    # load environment variables
    try:
        import dotenv
    except ImportError:
        logging.warning("dotenv not found, install using `pip install dotenv`")
    else:
        dotenv.load_dotenv()

# https://stackoverflow.com/a/76636817


def format_time_ago(delta: float) -> str:
    """Return time difference as human-readable string"""
    periods = (
        ("year", 60 * 60 * 24 * 365),
        ("month", 60 * 60 * 24 * 30),
        ("week", 60 * 60 * 24 * 7),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    )

    for period, seconds_each in periods:
        if delta >= seconds_each:
            how_many = int(delta / seconds_each)
            return f"{how_many} {period}{'s' if how_many >= 2 else ''} ago"

    return "just now"  # less than a second ago


class ImageCache:
    CACHE_DIR = os.path.join(".cache", "images")

    def __init__(self, image_bytes: Optional[bytes] = None, hash_value: Optional[str] = None):
        assert image_bytes or hash_value, "Either image_bytes or hash_value must be provided."
        assert not (image_bytes and hash_value), "Only one of image_bytes or hash_value should be provided."

        self.hash = None
        self.cached_image_bytes = None

        if image_bytes is not None:
            assert isinstance(image_bytes, bytes), "image_bytes must be of type bytes."
            assert len(image_bytes) > 0, "image_bytes cannot be empty."
            self.hash = self.compute_hash(image_bytes)
            self.cached_image_bytes = self.optimize_image(Image.open(io.BytesIO(image_bytes)))
            self.save_to_cache()

        if hash_value is not None:
            assert isinstance(hash_value, str), "hash_value must be of type str."
            assert len(hash_value) > 0, "hash_value cannot be empty."
            self.hash = hash_value

    @staticmethod
    def compute_hash(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()

    @property
    def cache_path(self) -> Optional[str]:
        if self.hash:
            return os.path.join(self.CACHE_DIR, f"{self.hash}.jpeg")
        return None

    def optimize_image(self, image: Image.Image) -> bytes:
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((512, 512), Image.Resampling.BILINEAR)
        with io.BytesIO() as output:
            image.save(output, format="JPEG", quality=75)
            image_bytes = output.getvalue()
        return image_bytes

    def save_to_cache(self):
        if not exists(self.cached_image_bytes):
            return
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        path = self.cache_path
        if path and not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(self.cached_image_bytes)

    @classmethod
    def from_dict(cls, data: dict):
        if not (hash_value := data.get("hash")):
            raise ValueError("Hash value is required to load ImageCache instance.")
        return cls(hash_value=hash_value)

    def to_dict(self) -> dict:
        return dict(hash=self.hash)

    def exists(self) -> bool:
        path = self.cache_path
        return exists(path) and os.path.exists(path)

    def get_bytes(self) -> Optional[bytes]:
        if exists(self.cached_image_bytes):
            return self.cached_image_bytes
        path = self.cache_path
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                self.cached_image_bytes = f.read()
        else:
            raise FileNotFoundError("Image not found in cache.")
        return self.cached_image_bytes

    def get_base64(self) -> Optional[str]:
        if exists(optimized_image_bytes := self.get_bytes()):
            return b64encode(optimized_image_bytes).decode("utf-8")
        return None

    def to_data_image_url(self) -> str:
        if exists(image_base64 := self.get_base64()):
            return f"data:image/jpeg;base64,{image_base64}"
        return None


class Ansi(StrEnum):
    END = '\33[0m'
    BOLD = '\33[1m'
    ITALIC = '\33[3m'
    URL = '\33[4m'
    BLINK = '\33[5m'
    BLINK2 = '\33[6m'
    SELECTED = '\33[7m'

    BLACK = '\33[30m'
    RED = '\33[31m'
    GREEN = '\33[32m'
    YELLOW = '\33[33m'
    BLUE = '\33[34m'
    VIOLET = '\33[35m'
    BEIGE = '\33[36m'
    WHITE = '\33[37m'

    BLACKBG = '\33[40m'
    REDBG = '\33[41m'
    GREENBG = '\33[42m'
    YELLOWBG = '\33[43m'
    BLUEBG = '\33[44m'
    VIOLETBG = '\33[45m'
    BEIGEBG = '\33[46m'
    WHITEBG = '\33[47m'

    GREY = '\33[90m'
    RED2 = '\33[91m'
    GREEN2 = '\33[92m'
    YELLOW2 = '\33[93m'
    BLUE2 = '\33[94m'
    VIOLET2 = '\33[95m'
    BEIGE2 = '\33[96m'
    WHITE2 = '\33[97m'

    GREYBG = '\33[100m'
    REDBG2 = '\33[101m'
    GREENBG2 = '\33[102m'
    YELLOWBG2 = '\33[103m'
    BLUEBG2 = '\33[104m'
    VIOLETBG2 = '\33[105m'
    BEIGEBG2 = '\33[106m'
    WHITEBG2 = '\33[107m'
