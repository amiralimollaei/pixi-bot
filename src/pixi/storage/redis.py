import json
from collections.abc import Iterator, Sequence

from redis.client import Redis

from ..model.chat import ChatMessageMeta
from ..model.storage.document import DocumentMeta
from .knowledge_disk import _deserialize_document, _serialize_documents


class MessagesRedisStorage:
    """Store message histories as incrementally appended JSON values in Redis."""

    _SENTINEL = "__pixi_messages_v2_history_start__"
    _PAGE_SIZE = 64

    _APPEND_SCRIPT = """
    if redis.call('EXISTS', KEYS[1]) == 0 then
        redis.call('RPUSH', KEYS[1], ARGV[1])
    end
    for i = 2, #ARGV do
        redis.call('RPUSH', KEYS[1], ARGV[i])
    end
    return 1
    """

    _TRUNCATE_SCRIPT = """
    if redis.call('EXISTS', KEYS[1]) == 0 then
        return 0
    end
    local keep = tonumber(ARGV[1]) + 1
    local length = redis.call('LLEN', KEYS[1])
    if keep < length then
        redis.call('LTRIM', KEYS[1], 0, keep - 1)
    end
    return 1
    """

    def __init__(self, url: str, *, key_prefix: str = "pixi:messages:"):
        self._client = Redis.from_url(url)
        self.key_prefix = key_prefix

    def _key(self, key: str) -> str:
        return f"{self.key_prefix}v2:{key}"

    def exists(self, key: str) -> bool:
        return bool(self._client.exists(self._key(key)))

    def count(self, key: str) -> int:
        length = self._client.llen(self._key(key))
        return max(0, length - 1)

    def append(self, key: str, messages: Sequence[ChatMessageMeta]) -> None:
        # Serialize the complete batch before the atomic Redis mutation.
        serialized = [
            json.dumps(message.to_dict(), ensure_ascii=False) for message in messages
        ]
        self._client.eval(
            self._APPEND_SCRIPT,
            1,
            self._key(key),
            self._SENTINEL,
            *serialized,
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
        key_name = self._key(key)
        length = max(0, self._client.llen(key_name) - 1)
        end = length if stop is None else min(stop, length)
        if end <= start:
            return

        if reverse:
            page_end = end
            while page_end > start:
                page_start = max(start, page_end - self._PAGE_SIZE)
                rows = self._client.lrange(key_name, page_start + 1, page_end)
                for row in reversed(rows):
                    yield self._decode_message(row)
                page_end = page_start
        else:
            page_start = start
            while page_start < end:
                page_end = min(end, page_start + self._PAGE_SIZE)
                rows = self._client.lrange(key_name, page_start + 1, page_end)
                for row in rows:
                    yield self._decode_message(row)
                page_start = page_end

    @staticmethod
    def _decode_message(data: bytes | str) -> ChatMessageMeta:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return ChatMessageMeta.from_dict(json.loads(data))

    def truncate(self, key: str, length: int) -> None:
        if length < 0:
            raise ValueError("length must be nonnegative")
        self._client.eval(self._TRUNCATE_SCRIPT, 1, self._key(key), length)

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def close(self) -> None:
        self._client.close()


class KnowledgeRedisStorage:
    """Persist each named snapshot as a single atomically replaced Redis value."""

    # Keep the persisted key prefix stable across terminology changes.
    def __init__(self, url: str, *, key_prefix: str = "pixi:datasets:"):
        self._client = Redis.from_url(url)
        self.key_prefix = key_prefix

    def _key(self, name: str) -> str:
        return f"{self.key_prefix}{name}"

    def load(self, name: str) -> list[DocumentMeta]:
        payload = self._client.get(self._key(name))
        if payload is None:
            return []
        documents = [
            _deserialize_document(document)
            for document in json.loads(payload)
        ]
        return sorted(documents, key=lambda document: document.id)

    def save(self, name: str, documents: Sequence[DocumentMeta]) -> None:
        serialized = _serialize_documents(documents)
        if not serialized:
            self.delete(name)
            return
        payload = "[" + ",".join(payload for _, payload in serialized) + "]"
        self._client.set(self._key(name), payload)

    def delete(self, name: str) -> None:
        self._client.delete(self._key(name))

    def close(self) -> None:
        self._client.close()
