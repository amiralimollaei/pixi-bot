from collections.abc import Iterator, Sequence
from typing import Protocol

from ..model.chat import ChatMessageMeta


class MessagesStorage(Protocol):
    """Ordered, incremental message storage; never a whole-history snapshot."""

    def exists(self, key: str) -> bool:
        """Distinguish an absent history from an existing empty history."""
        ...

    def count(self, key: str) -> int:
        """Return the message count, or zero for an absent history."""
        ...

    def append(self, key: str, messages: Sequence[ChatMessageMeta]) -> None:
        """Atomically append a batch; an empty batch creates an empty history."""
        ...

    def iter_messages(
        self, key: str, *, start: int = 0, stop: int | None = None, reverse: bool = False,
    ) -> Iterator[ChatMessageMeta]:
        """Read [start, stop) lazily in either order using bounded pages.

        Bounds are nonnegative. An omitted stop captures the current count;
        subsequent appends are not included. Missing histories yield nothing.
        """
        ...

    def truncate(self, key: str, length: int) -> None:
        """Drop the tail at length, without growing or creating a history."""
        ...

    def delete(self, key: str) -> None:
        """Delete a history; deleting an absent key is a no-op."""
        ...
