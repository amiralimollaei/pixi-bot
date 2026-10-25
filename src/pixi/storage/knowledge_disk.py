import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import zstandard

from pixi.model.storage.document import DocumentMeta


def _serialize_documents(documents: Sequence[DocumentMeta]) -> list[tuple[int, str]]:
    """Validate and encode a complete snapshot before a backend mutates storage."""
    serialized = []
    seen = set()
    for document in documents:
        if not isinstance(document, DocumentMeta):
            raise TypeError("knowledge documents must be DocumentMeta instances")
        if type(document.id) is not int:
            raise TypeError("document IDs must be integers")
        if document.id in seen:
            raise ValueError(f"duplicate document ID: {document.id}")
        if not isinstance(document.title, str) or not isinstance(document.content, str):
            raise TypeError("document titles and content must be strings")
        if document.source is not None and not isinstance(document.source, str):
            raise TypeError("document sources must be strings or None")
        payload = json.dumps(asdict(document), ensure_ascii=False)
        payload.encode("utf-8")
        serialized.append((document.id, payload))
        seen.add(document.id)
    return sorted(serialized, key=lambda item: item[0])


def _deserialize_document(payload: str | bytes | dict) -> DocumentMeta:
    data = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
    return DocumentMeta(
        title=data["title"],
        content=data["content"],
        id=int(data["id"]),
        source=data.get("source"),
    )


class KnowledgeDiskStorage:
    """Store snapshots as compressed JSON documents under a knowledge root.

    Existing hash-named .zst documents remain readable. A save replaces them
    with ID-named files and removes every obsolete .zst document. Complete batch
    encoding and compression precede filesystem mutation; individual file
    replacement is atomic, but concurrent readers/writers need external locking.
    """

    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory).resolve()

    def _knowledge_path(self, name: str) -> Path:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or any(character in name for character in ("/", "\\", "\0"))
        ):
            raise ValueError(
                "knowledge-base names must be nonempty single path components"
            )
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ValueError("knowledge paths must stay within the knowledge root")
        return path

    def load(self, name: str) -> list[DocumentMeta]:
        path = self._knowledge_path(name)
        documents = {}
        for file in sorted(path.glob("*.zst")):
            if file.is_symlink():
                raise ValueError("knowledge documents must not be symbolic links")
            document = _deserialize_document(zstandard.decompress(file.read_bytes()))
            # Old saves could leave multiple hash-named versions of an ID.
            # Resolve those consistently; the next save removes the duplicates.
            documents[document.id] = document
        return [documents[id] for id in sorted(documents)]

    def save(self, name: str, documents: Sequence[DocumentMeta]) -> None:
        path = self._knowledge_path(name)
        compressed = [
            (f"{id}.zst", zstandard.compress(payload.encode("utf-8")))
            for id, payload in _serialize_documents(documents)
        ]
        if not compressed:
            self.delete(name)
            return

        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".pixi-knowledge-", dir=self.directory
        ) as staging:
            staging_path = Path(staging)
            for filename, payload in compressed:
                (staging_path / filename).write_bytes(payload)
            path.mkdir(exist_ok=True)
            for filename, _ in compressed:
                os.replace(staging_path / filename, path / filename)
            filenames = {filename for filename, _ in compressed}
            for file in path.glob("*.zst"):
                if file.name not in filenames:
                    file.unlink()

    def delete(self, name: str) -> None:
        path = self._knowledge_path(name)
        for file in path.glob("*.zst"):
            file.unlink()
