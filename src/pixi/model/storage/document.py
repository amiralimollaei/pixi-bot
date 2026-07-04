from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentMeta:
    title: str
    content: str
    id: int
    source: str | None = None

    def __hash__(self):
        return hash(self.content)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DocumentMeta):
            return NotImplemented
        return self.content == other.content
