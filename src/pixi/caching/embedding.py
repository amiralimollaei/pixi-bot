import array
import hashlib
import os
from typing import Optional

from ..storage.paths import PixiPaths


class EmbeddingCache:
    """
    Automatically caches the embedding vectors if initialized with `vec` and automatically
    loads the cahced embedding vectors if not initialized with `vec`, raises OSError if the
    cache file does not exist or cannot be read.
    """

    def __init__(self, text: str, dim: int, vec: Optional[array.array[float]] = None):
        self.text = text
        self.dim = dim
        self.vec = vec

        cache_dir = PixiPaths.cache() / "embeddings"

        if self.vec is None:
            # loads the cached vector
            self.load()
        else:
            assert self.vec.typecode == "f"
            # caches the vector
            if not os.path.exists(self.get_save_path(self.hash_hexdigest)):
                os.makedirs(cache_dir, exist_ok=True)
                self.save()

    @property
    def hash_hexdigest(self):
        return hashlib.sha256(f"{self.text}@{self.dim}".encode("utf-8")).hexdigest()

    @staticmethod
    def get_save_path(hash: str):
        return str(PixiPaths.cache() / "embeddings" / f"{hash}.npz")

    def save(self):
        assert self.vec is not None
        with open(self.get_save_path(self.hash_hexdigest), "wb") as f:
            f.write(self.vec.tobytes())

    def load(self):
        vec = array.array("f")
        with open(self.get_save_path(self.hash_hexdigest), "rb") as f:
            vec.frombytes(f.read())
        self.vec = vec
