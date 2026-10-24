import hashlib
from pathlib import Path

from . import InMemoryCache


class CacheDiskStorage:
    """Persist cache values under hashed namespaces and binary keys."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _path(self, hash: bytes, namespace: str) -> Path:
        namespace_hash = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        key_hash = hashlib.sha256(hash).hexdigest()
        return self.directory / namespace_hash / key_hash

    def write(self, cache: InMemoryCache, hash: bytes, *, namespace: str) -> None:
        data = cache.to_bytes()
        path = self._path(hash, namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def exists(self, hash: bytes, *, namespace: str) -> bool:
        return self._path(hash, namespace).is_file()

    def read(self, hash: bytes, *, namespace: str) -> InMemoryCache | None:
        try:
            data = self._path(hash, namespace).read_bytes()
        except FileNotFoundError:
            return None
        return InMemoryCache.from_bytes(data)
