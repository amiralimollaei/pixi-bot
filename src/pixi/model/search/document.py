from dataclasses import dataclass

from ..embedding import Embedding


@dataclass(frozen=True)
class QueryMatch:
    title: str
    id: int
    num_matches: int
    match_score: float
    source: str | None = None

    def __hash__(self) -> int:
        return hash((self.title, self.id, self.num_matches, self.match_score, self.source))


@dataclass(frozen=True)
class DocumentReference:
    id: int
    name: str


@dataclass(frozen=True)
class VectorTextPiece:
    data: Embedding
    reference: DocumentReference

    @property
    def vec(self): return self.data.vec
    @property
    def text(self): return self.data.text


@dataclass(frozen=True)
class TextPieceMatch:
    text: str
    similarity_score: float
    reference: DocumentReference
