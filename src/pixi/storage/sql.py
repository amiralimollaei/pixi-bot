import hashlib
import json
from collections.abc import Iterator, Sequence

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    case,
    create_engine,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import LONGTEXT, insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url

from ..model.chat import ChatMessageMeta
from ..model.storage.document import DocumentMeta
from .knowledge_disk import _deserialize_document, _serialize_documents


class MessagesSQLStorage:
    """Store histories as independently addressable SQL message rows."""

    _PAGE_SIZE = 64

    def __init__(self, url: str):
        parsed_url = make_url(url)
        if parsed_url.drivername in {"postgres", "postgresql"}:
            parsed_url = parsed_url.set(drivername="postgresql+psycopg")
        engine = create_engine(parsed_url)
        try:
            metadata = MetaData()
            heads = Table(
                "pixi_history_heads",
                metadata,
                Column("key_hash", String(64), primary_key=True),
                Column("length", Integer, nullable=False),
            )
            messages = Table(
                "pixi_history_messages",
                metadata,
                Column("key_hash", String(64), primary_key=True),
                Column("position", Integer, primary_key=True),
                Column(
                    "payload",
                    Text().with_variant(LONGTEXT(), "mysql", "mariadb"),
                    nullable=False,
                ),
            )
            metadata.create_all(engine)
        except BaseException:
            engine.dispose()
            raise

        self._engine = engine
        self._heads = heads
        self._messages = messages

    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _ensure_head(self, connection, key_hash: str) -> None:
        dialect = self._engine.dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(self._heads).values(key_hash=key_hash, length=0)
            statement = statement.on_conflict_do_nothing(
                index_elements=[self._heads.c.key_hash]
            )
        elif dialect == "postgresql":
            statement = postgresql_insert(self._heads).values(
                key_hash=key_hash, length=0
            )
            statement = statement.on_conflict_do_update(
                index_elements=[self._heads.c.key_hash],
                set_={"key_hash": statement.excluded.key_hash},
            )
        elif dialect in {"mysql", "mariadb"}:
            statement = mysql_insert(self._heads).values(key_hash=key_hash, length=0)
            statement = statement.on_duplicate_key_update(
                key_hash=statement.inserted.key_hash
            )
        else:
            try:
                with connection.begin_nested():
                    connection.execute(
                        self._heads.insert().values(key_hash=key_hash, length=0)
                    )
            except IntegrityError:
                exists = connection.execute(
                    select(self._heads.c.key_hash)
                    .where(self._heads.c.key_hash == key_hash)
                    .with_for_update()
                ).first()
                if exists is None:
                    raise
            return
        connection.execute(statement)

    def exists(self, key: str) -> bool:
        with self._engine.connect() as connection:
            return connection.execute(
                select(self._heads.c.key_hash).where(
                    self._heads.c.key_hash == self._key_hash(key)
                )
            ).first() is not None

    def count(self, key: str) -> int:
        with self._engine.connect() as connection:
            length = connection.execute(
                select(self._heads.c.length).where(
                    self._heads.c.key_hash == self._key_hash(key)
                )
            ).scalar_one_or_none()
        return 0 if length is None else length

    def append(self, key: str, messages: Sequence[ChatMessageMeta]) -> None:
        payloads = [
            json.dumps(message.to_dict(), ensure_ascii=False) for message in messages
        ]
        key_hash = self._key_hash(key)
        with self._engine.begin() as connection:
            self._ensure_head(connection, key_hash)
            if not payloads:
                return
            connection.execute(
                update(self._heads)
                .where(self._heads.c.key_hash == key_hash)
                .values(length=self._heads.c.length + len(payloads))
            )
            end = connection.execute(
                select(self._heads.c.length).where(
                    self._heads.c.key_hash == key_hash
                )
            ).scalar_one()
            first = end - len(payloads)
            connection.execute(
                self._messages.insert(),
                [
                    {
                        "key_hash": key_hash,
                        "position": first + offset,
                        "payload": payload,
                    }
                    for offset, payload in enumerate(payloads)
                ],
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
            raise ValueError("message bounds must be nonnegative")

        key_hash = self._key_hash(key)
        if stop is None:
            stop = self.count(key)
        if start >= stop:
            return

        if reverse:
            cursor = stop
            while cursor > start:
                with self._engine.connect() as connection:
                    rows = connection.execute(
                        select(self._messages.c.position, self._messages.c.payload)
                        .where(
                            self._messages.c.key_hash == key_hash,
                            self._messages.c.position >= start,
                            self._messages.c.position < cursor,
                        )
                        .order_by(self._messages.c.position.desc())
                        .limit(self._PAGE_SIZE)
                    ).all()
                if not rows:
                    break
                cursor = rows[-1].position
                for row in rows:
                    yield ChatMessageMeta.from_dict(json.loads(row.payload))
        else:
            cursor = start
            while cursor < stop:
                with self._engine.connect() as connection:
                    rows = connection.execute(
                        select(self._messages.c.position, self._messages.c.payload)
                        .where(
                            self._messages.c.key_hash == key_hash,
                            self._messages.c.position >= cursor,
                            self._messages.c.position < stop,
                        )
                        .order_by(self._messages.c.position)
                        .limit(self._PAGE_SIZE)
                    ).all()
                if not rows:
                    break
                cursor = rows[-1].position + 1
                for row in rows:
                    yield ChatMessageMeta.from_dict(json.loads(row.payload))

    def truncate(self, key: str, length: int) -> None:
        if length < 0:
            raise ValueError("history length must be nonnegative")
        key_hash = self._key_hash(key)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(self._heads)
                .where(self._heads.c.key_hash == key_hash)
                .values(
                    length=case(
                        (self._heads.c.length > length, length),
                        else_=self._heads.c.length,
                    )
                )
            )
            if result.rowcount == 0:
                return
            connection.execute(
                self._messages.delete().where(
                    self._messages.c.key_hash == key_hash,
                    self._messages.c.position >= length,
                )
            )

    def delete(self, key: str) -> None:
        key_hash = self._key_hash(key)
        with self._engine.begin() as connection:
            result = connection.execute(
                self._heads.delete().where(self._heads.c.key_hash == key_hash)
            )
            if result.rowcount == 0:
                return
            connection.execute(
                self._messages.delete().where(self._messages.c.key_hash == key_hash)
            )

    def close(self) -> None:
        self._engine.dispose()


class KnowledgeSQLStorage:
    """Persist each named snapshot in one row so concurrent saves cannot mix documents."""

    def __init__(self, url: str):
        parsed_url = make_url(url)
        if parsed_url.drivername in {"postgres", "postgresql"}:
            parsed_url = parsed_url.set(drivername="postgresql+psycopg")
        engine = create_engine(parsed_url)
        try:
            metadata = MetaData()
            # Keep the persisted table name stable across terminology changes.
            snapshots = Table(
                "pixi_dataset_snapshots",
                metadata,
                Column("name_hash", String(64), primary_key=True),
                Column(
                    "payload",
                    Text().with_variant(LONGTEXT(), "mysql", "mariadb"),
                    nullable=False,
                ),
            )
            metadata.create_all(engine)
        except BaseException:
            engine.dispose()
            raise
        self._engine = engine
        self._snapshots = snapshots

    @staticmethod
    def _name_hash(name: str) -> str:
        return hashlib.sha256(name.encode("utf-8")).hexdigest()

    def load(self, name: str) -> list[DocumentMeta]:
        with self._engine.connect() as connection:
            payload = connection.execute(
                select(self._snapshots.c.payload).where(
                    self._snapshots.c.name_hash == self._name_hash(name)
                )
            ).scalar_one_or_none()
        if payload is None:
            return []
        return [_deserialize_document(document) for document in json.loads(payload)]

    def save(self, name: str, documents: Sequence[DocumentMeta]) -> None:
        serialized = _serialize_documents(documents)
        if not serialized:
            self.delete(name)
            return
        payload = "[" + ",".join(payload for _, payload in serialized) + "]"
        name_hash = self._name_hash(name)
        table = self._snapshots
        values = {"name_hash": name_hash, "payload": payload}
        dialect = self._engine.dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(table).values(**values).on_conflict_do_update(
                index_elements=[table.c.name_hash], set_={"payload": payload}
            )
        elif dialect == "postgresql":
            statement = postgresql_insert(table).values(**values).on_conflict_do_update(
                index_elements=[table.c.name_hash], set_={"payload": payload}
            )
        elif dialect in {"mysql", "mariadb"}:
            statement = mysql_insert(table).values(**values).on_duplicate_key_update(
                payload=payload
            )
        else:
            statement = None
        with self._engine.begin() as connection:
            if statement is not None:
                connection.execute(statement)
            else:
                connection.execute(table.delete().where(table.c.name_hash == name_hash))
                connection.execute(table.insert().values(**values))

    def delete(self, name: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                self._snapshots.delete().where(
                    self._snapshots.c.name_hash == self._name_hash(name)
                )
            )

    def close(self) -> None:
        self._engine.dispose()
