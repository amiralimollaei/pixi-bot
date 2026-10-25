from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol

from pixi.model.storage.document import DocumentMeta


class KnowledgeStorage(Protocol):
    """Persist whole named knowledge-base snapshots, not incremental histories."""

    def load(self, name: str) -> list[DocumentMeta]:
        """Return documents ordered by ascending ID, or [] for a missing knowledge base."""
        ...

    def save(self, name: str, documents: Sequence[DocumentMeta]) -> None:
        """Replace the knowledge base, preserving all fields and removing stale documents.

        IDs must be unique integers; titles/content must be strings and sources
        must be strings or None. Validate the whole batch before changing storage.
        """
        ...

    def delete(self, name: str) -> None:
        """Delete the knowledge base; deleting a missing knowledge base is a no-op."""
        ...


class KnowledgeImporter(Protocol):
    """Read a local source independently of storage, bot state, or inference."""

    def read_documents(self, path: Path) -> Iterator[DocumentMeta]:
        """Yield nonempty documents with unique, deterministic integer IDs.

        Preserve titles and source references where available. The same source
        must produce the same documents on repeated calls; importer instances
        must not retain per-import state. Implementations own their source
        resources and release them when the iterator is exhausted or closed.

        Invalid sources raise an exception, possibly during iteration. Callers
        must exhaust the iterator before persisting a replacement snapshot.
        Importers must never mutate knowledge storage.
        """
        ...
