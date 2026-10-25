import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path

from pixi.model.chat import ChatMessageMeta


class MessagesDiskStorage:
    """Store individual messages in an indexed SQLite file without extra dependencies."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "messages.sqlite3"
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS histories (key_hash TEXT PRIMARY KEY, length INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "key_hash TEXT NOT NULL, position INTEGER NOT NULL, payload TEXT NOT NULL, "
                "PRIMARY KEY (key_hash, position))"
            )

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            with connection:
                yield connection

    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def exists(self, key: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM histories WHERE key_hash = ?",
                    (self._key_hash(key),),
                ).fetchone()
                is not None
            )

    def count(self, key: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT length FROM histories WHERE key_hash = ?",
                (self._key_hash(key),),
            ).fetchone()
        return row[0] if row is not None else 0

    def append(self, key: str, messages: Sequence[ChatMessageMeta]) -> None:
        payloads = [
            json.dumps(message.to_dict(), ensure_ascii=False) for message in messages
        ]
        key_hash = self._key_hash(key)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO histories (key_hash, length) VALUES (?, 0)",
                (key_hash,),
            )
            if not payloads:
                return
            connection.execute(
                "UPDATE histories SET length = length + ? WHERE key_hash = ?",
                (len(payloads), key_hash),
            )
            end = connection.execute(
                "SELECT length FROM histories WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO messages (key_hash, position, payload) VALUES (?, ?, ?)",
                (
                    (key_hash, position, payload)
                    for position, payload in enumerate(payloads, end - len(payloads))
                ),
            )

    def iter_messages(
        self,
        key: str,
        *,
        start: int = 0,
        stop: int | None = None,
        reverse: bool = False,
    ) -> Iterator[ChatMessageMeta]:
        if start < 0 or (stop is not None and stop < 0):
            raise ValueError("History bounds must be nonnegative.")
        end = self.count(key) if stop is None else stop
        key_hash = self._key_hash(key)
        order = "DESC" if reverse else "ASC"
        while start < end:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT position, payload FROM messages "
                    f"WHERE key_hash = ? AND position >= ? AND position < ? ORDER BY position {order} LIMIT 32",
                    (key_hash, start, end),
                ).fetchall()
            if not rows:
                return
            if reverse:
                end = rows[-1][0]
            else:
                start = rows[-1][0] + 1
            for _, payload in rows:
                yield ChatMessageMeta.from_dict(json.loads(payload))

    def truncate(self, key: str, length: int) -> None:
        if length < 0:
            raise ValueError("History length must be nonnegative.")
        key_hash = self._key_hash(key)
        with self._connect() as connection:
            connection.execute(
                "UPDATE histories SET length = MIN(length, ?) WHERE key_hash = ?",
                (length, key_hash),
            )
            connection.execute(
                "DELETE FROM messages WHERE key_hash = ? AND position >= ?",
                (key_hash, length),
            )

    def delete(self, key: str) -> None:
        key_hash = self._key_hash(key)
        with self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE key_hash = ?", (key_hash,))
            connection.execute("DELETE FROM histories WHERE key_hash = ?", (key_hash,))
