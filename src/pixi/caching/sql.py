import hashlib

from sqlalchemy import (
    Column,
    LargeBinary,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
)
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url

from pixi.caching import InMemoryCache


class CacheSQLStorage:
    """Persist serialized cache entries in SQL, isolated by namespace and key."""

    def __init__(self, url: str):
        parsed_url = make_url(url)
        if parsed_url.drivername in {"postgres", "postgresql"}:
            parsed_url = parsed_url.set(drivername="postgresql+psycopg")
        engine = create_engine(parsed_url)
        try:
            metadata = MetaData()
            entries = Table(
                "pixi_cache_entries",
                metadata,
                Column("key_hash", String(64), primary_key=True),
                Column(
                    "payload",
                    LargeBinary().with_variant(LONGBLOB(), "mysql", "mariadb"),
                    nullable=False,
                ),
            )
            metadata.create_all(engine)
        except BaseException:
            engine.dispose()
            raise
        self._engine = engine
        self._table = entries

    @staticmethod
    def _key_hash(hash: bytes, namespace: str) -> str:
        namespace_bytes = namespace.encode("utf-8")
        key = len(namespace_bytes).to_bytes(8, "big") + namespace_bytes + hash
        return hashlib.sha256(key).hexdigest()

    def write(self, cache: InMemoryCache, hash: bytes, *, namespace: str) -> None:
        payload = cache.to_bytes()
        key_hash = self._key_hash(hash, namespace)
        table = self._table
        values = {"key_hash": key_hash, "payload": payload}
        dialect = self._engine.dialect.name
        if dialect == "sqlite":
            statement = (
                sqlite_insert(table)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[table.c.key_hash], set_={"payload": payload}
                )
            )
        elif dialect == "postgresql":
            statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[table.c.key_hash], set_={"payload": payload}
                )
            )
        elif dialect in {"mysql", "mariadb"}:
            statement = (
                mysql_insert(table)
                .values(**values)
                .on_duplicate_key_update(payload=payload)
            )
        else:
            statement = None
        with self._engine.begin() as connection:
            if statement is not None:
                connection.execute(statement)
            else:
                connection.execute(delete(table).where(table.c.key_hash == key_hash))
                connection.execute(insert(table).values(**values))

    def exists(self, hash: bytes, *, namespace: str) -> bool:
        with self._engine.connect() as connection:
            result = connection.execute(
                select(self._table.c.key_hash).where(
                    self._table.c.key_hash == self._key_hash(hash, namespace)
                )
            ).first()
        return result is not None

    def read(self, hash: bytes, *, namespace: str) -> InMemoryCache | None:
        with self._engine.connect() as connection:
            payload = connection.execute(
                select(self._table.c.payload).where(
                    self._table.c.key_hash == self._key_hash(hash, namespace)
                )
            ).scalar_one_or_none()
        return None if payload is None else InMemoryCache.from_bytes(bytes(payload))

    def close(self) -> None:
        self._engine.dispose()
