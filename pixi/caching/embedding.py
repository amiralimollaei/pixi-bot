import os
import hashlib
from typing import Optional

import numpy as np

from ..utils import PixiPaths


class EmbedingCache:
    """
    Automatically caches the embedding vectors if initialized with `vec` and automatically
    loads the cahced embedding vectors if not initialized with `vec`, raises OSError if the
    cache file does not exist or cannot be read.
    """

    def __init__(self, text: str, dim: int, vec: Optional[np.ndarray] = None):
        self.text = text
        self.dim = dim
        self.vec = vec

        cache_dir = PixiPaths.cache() / "embeddings"

        if self.vec is None:
            # loads the cached vector
            self.load()
        else:
            # caches the vector
            os.makedirs(cache_dir, exist_ok=True)
            self.save()

    @property
    def hash_hexdigest(self):
        return hashlib.sha256(str(dict(text=self.text, dim=self.dim)).encode("utf-8")).hexdigest()

    @staticmethod
    def get_save_path(hash: str):
        return str(PixiPaths.cache() / "embeddings" / f"{hash}.npz")

    def save(self):
        assert self.vec is not None
        return np.savez_compressed(self.get_save_path(self.hash_hexdigest), vec=self.vec)

    def load(self):
        data = np.load(self.get_save_path(self.hash_hexdigest))
        self.vec = data["vec"]
