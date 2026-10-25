from collections.abc import Sequence
from typing import Protocol

from ..model.storage.document import DocumentMeta


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
