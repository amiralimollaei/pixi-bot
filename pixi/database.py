import dataclasses
from glob import glob
import hashlib
import json
import os
import re

import httpx
import numpy as np
import openai
import zstandard

from .utils import PixiPaths
from .caching import EmbedingCache
from .config import OpenAIAuthConfig, OpenAIEmbeddingModelConfig


@dataclasses.dataclass(frozen=True)
class DatasetEntry:
    title: str
    content: str
    id: int
    source: str | None = None

    def __hash__(self):
        return hash(self.content)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DatasetEntry):
            return NotImplemented
        return self.content == other.content


@dataclasses.dataclass(frozen=True)
class QueryMatch:
    title: str
    id: int
    num_matches: int
    match_score: float
    source: str | None = None

    def __hash__(self) -> int:
        return hash((self.title, self.id, self.num_matches, self.match_score, self.source))


class DocumentDataset:
    def __init__(self, data: dict[int, DatasetEntry] | None = None):
        if data:
            assert isinstance(data, dict), f"expected data to be of type `dict` but got `{data}`"
            for e in data.values():
                if isinstance(e, DatasetEntry):
                    continue
                raise TypeError(f"expetced all elements to be of type `DatasetEntry` but got `{type(e)}`")
        self.data = data or dict()

    def add_entry(self, title: str, text: str, source: str | None = None):
        text = text.strip(" \n\r\t")
        if not text:
            return

        entry = DatasetEntry(
            title=title,
            content=text,
            id=len(self.data),
            source=source
        )

        self.data.update({entry.id: entry})

    def get(self, id: int):
        return self.data.get(id)

    async def search(self, query: str, best_n: int = 10) -> list[QueryMatch]:
        """
        Searches through self.data for entries matching the query terms.

        This search is case-insensitive and ignores punctuation.
        It generates snippets of text around each match.
        """

        # 1. Pre-process the query for efficiency.
        #    - Split into words, lowercase, and convert to a set for O(1) lookups.
        query_words = set(re.split(r"[^\w]+", query.lower()))
        search_terms = query_words

        if not search_terms:
            return []

        all_matches: set[QueryMatch] = set()

        # 2. Iterate through each entry in the dataset.
        for entry in self.data.values():
            if not entry.content:
                continue

            # 3. Tokenize entry content while preserving delimiters (for reconstruction).
            content_parts = re.split(r"([^\w])", entry.content)

            # 4. Identify which parts are matches. This avoids repeated regex and lookups.
            match_flags = [
                len(part) > 1 and re.sub(r"[^\w]", "", part).lower() in search_terms
                for part in content_parts
            ]

            num_matches = sum(match_flags)
            if num_matches == 0:
                continue

            all_matches.add(QueryMatch(
                title=entry.title,
                id=entry.id,
                source=entry.source,
                num_matches=num_matches,
                match_score=(num_matches/len(content_parts)) * 100,
            ))

        # 6. Sort results by relevance (num_matches) once at the end and return the best matches.
        return sorted(all_matches, key=lambda m: m.num_matches, reverse=True)[:best_n]


class DirectoryDatabase:
    def __init__(self, directory: str, dataset: DocumentDataset | None = None):
        self.directory = directory
        self.dataset = dataset or DocumentDataset()

    async def search(self, query: str, best_n: int = 10) -> list[QueryMatch]:
        return await self.dataset.search(query=query, best_n=best_n)

    async def get_entry(self, id: int) -> DatasetEntry:
        entry = self.dataset.get(id=id)
        if entry is None:
            raise KeyError(f"No entry found with {id=}")
        return entry

    @classmethod
    def from_directory(cls, directory: str):
        assert directory

        full_dir = cls.get_dataset_directory(directory)

        if not os.path.isdir(full_dir):
            dataset = DocumentDataset()
            return cls(directory=directory, dataset=dataset)

        data = dict()
        for file in glob(str(full_dir / "*.zst")):
            with open(file, mode='rb') as f:
                json_data = zstandard.decompress(f.read())
                entry_data = json.loads(json_data)
                entry = DatasetEntry(
                    title=entry_data['title'],
                    content=entry_data['content'],
                    id=int(entry_data['id']),
                    source=entry_data.get('source')
                )
                data.update({entry.id: entry})
        dataset = DocumentDataset(data)
        return cls(directory=directory, dataset=dataset)

    @classmethod
    def get_dataset_directory(cls, directory):
        return PixiPaths.datasets() / directory

    def clear(self):
        full_dir = DirectoryDatabase.get_dataset_directory(self.directory)
        for file in glob(str(full_dir / "*.zst")):
            if os.path.isfile(file):
                os.remove(file)

    def save(self):
        assert self.dataset, "dataset is not initialized, nothing to save"

        full_dir = DirectoryDatabase.get_dataset_directory(self.directory)

        os.makedirs(full_dir, exist_ok=True)

        for entry in self.dataset.data.values():
            entry_hash = self.get_entry_hash(entry).hexdigest()
            with open(full_dir / f"{entry_hash}.zst", mode='wb') as f:
                json_data = json.dumps(dict(
                    title=entry.title,
                    content=entry.content,
                    id=entry.id,
                    source=entry.source or ""
                ), ensure_ascii=False)
                f.write(zstandard.compress(json_data.encode("utf-8")))

    def get_entry_hash(self, entry: DatasetEntry):
        return hashlib.sha256(
            (entry.content + entry.title + str(entry.source) + str(entry.id)).encode("utf-8")
        )

# constants


PARAGRAPH_SPLIT = re.compile(r"\n{2,}")
DEFAULT_MODEL = "BAAI/bge-m3-multi"


@dataclasses.dataclass(frozen=True)
class EmbeddedDocumentReference:
    id: int
    name: str


@dataclasses.dataclass(frozen=True)
class EmbeddedDocumentPiece:
    data: EmbedingCache
    reference: EmbeddedDocumentReference

    @property
    def vec(self):
        return self.data.vec

    @property
    def text(self):
        return self.data.text


@dataclasses.dataclass(frozen=True)
class DocumentPieceMatch:
    text: str
    similarity_score: float
    reference: EmbeddedDocumentReference


class SmartSplitter:
    def __init__(self, max_size=1024, min_size=256):
        # Ensure min_size makes sense relative to max_size
        self.max_size = max_size
        self.min_size = min(min_size, max_size // 2)

        self.separators = [
            r"\n\n+",         # Paragraphs
            r"\n",            # Newlines
            r"(?<=[.!?]) +",  # Sentences
            r"\|",            # Pipes (MediaWiki)
            r" +",            # Words
        ]

    def split(self, text: str) -> list[str]:
        if not text:
            return []

        # 1. Recursive Binary Split with "Safe Zones"
        # fragments must not be longer than max size, but may be smaller than min size
        fragments = self._initial_split(text)

        # 2. Greedy Merge
        # merges fragments that are smaller than min size to bigger fragments that are just less than max size
        chunks = self._greedy_merge(fragments)

        # 3. Re-balancing Pass
        # fixes last chunk being too small (we merged all the prevous fragments and the last fragments are merged into a small chunk)
        return self._rebalance(chunks)

    def _initial_split(self, text: str) -> list[str]:
        stack = [text]
        done = []

        while stack:
            current = stack.pop()
            if len(current) <= self.max_size:
                done.append(current)
                continue

            # Try to find a "Safe Split" (respects min_size on both sides)
            split_idx = self._find_best_split_point(current, safe=True)

            # Fallback: If no safe split exists, take the best available split
            if split_idx is None:
                split_idx = self._find_best_split_point(current, safe=False)

            left, right = current[:split_idx], current[split_idx:]
            stack.append(right)
            stack.append(left)

        return done

    def _find_best_split_point(self, text: str, safe: bool = True) -> int | None:
        mid = len(text) // 2

        for sep in self.separators:
            matches = list(re.finditer(sep, text))

            if safe:
                # A "Safe" index ensures both resulting chunks are >= min_size
                indices = [m.end() for m in matches if self.min_size <= m.end() <= len(text) - self.min_size]
            else:
                # A "Forced" index just avoids the absolute 0 or length
                indices = [m.end() for m in matches if 0 < m.end() < len(text)]

            if indices:
                return min(indices, key=lambda x: abs(x - mid))

        # If forced and no separator found, split exactly at middle
        return mid if not safe else None

    def _greedy_merge(self, fragments: list[str]) -> list[str]:
        if not fragments:
            return []
        merged = []
        current = fragments[0]

        for i in range(1, len(fragments)):
            f = fragments[i]
            if len(current) + len(f) <= self.max_size:
                current += f
            else:
                merged.append(current)
                current = f
        merged.append(current)
        return merged

    def _rebalance(self, chunks: list[str]) -> list[str]:
        """
        If the last chunk is too small, merge it with the previous and 
        re-split that combined block at the absolute best middle.
        """
        if len(chunks) < 2:
            return chunks

        # Check if the last chunk violates min_size
        if len(chunks[-1]) < self.min_size:
            last = chunks.pop()
            prev = chunks.pop()
            combined = prev + last

            # Case A: Combined is small enough to be one chunk
            if len(combined) <= self.max_size:
                chunks.append(combined)
            else:
                # Case B: Combined is too big; split it exactly in the middle
                # (ignoring safety) to create two balanced, large-enough chunks.
                split_idx = self._find_best_split_point(combined, safe=False)
                chunks.append(combined[:split_idx])
                chunks.append(combined[split_idx:])

        return chunks


class AsyncEmbeddingDatabase:
    def __init__(self, auth: OpenAIAuthConfig, model: OpenAIEmbeddingModelConfig):
        self.auth = auth
        self.model = model

        self.splitter = SmartSplitter(max_size=self.model.max_chunk_size, min_size=self.model.min_chunk_size)

        self.dataset: list[EmbeddedDocumentPiece] = []

        self.client = openai.AsyncOpenAI(
            base_url=self.auth.base_url,
            api_key=self.auth.api_key,
            # don't use proxies from environment variables
            http_client=httpx.AsyncClient(trust_env=False),
        )

    async def add_document_piece(self, input: str | list[str], reference: EmbeddedDocumentReference):
        embeddings = await self.embed(input)

        if isinstance(embeddings, EmbedingCache):
            embeddings = [embeddings]

        for embedding in embeddings:
            self.dataset.append(EmbeddedDocumentPiece(
                data=embedding,
                reference=reference
            ))

    async def add_document(
        self,
        text: str,
        name: str,
        id: int,
    ):
        """
        breaks the document into smaller pieses and adds them using `self.add_document_piece(...)`

        params:
            text: (str) the full text of the document to be porcessed
            name: (str) the name of the document used for referencing
            id: (int) the id of the document used for referencing

        returns:
            None
        """

        # replace any whitepsace that is repeated more than once with only one if its kind
        # except newline where we allow it to be repeated a maximum of 2 times.
        text = re.sub(r"(\n\n)\s+|(\s)\s+", r"\1", text)

        await self.add_document_piece(
            input=self.splitter.split(text.strip(" \n\r\t")),
            reference=EmbeddedDocumentReference(
                name=name,
                id=id
            )
        )

    async def embed(self, input: str | list[str]):
        assert self.model.dimension, "no embedding dimension specified"

        was_unbatched = False
        if isinstance(input, str):
            input = [input]
            was_unbatched = True

        missed_inputs = []
        results: list[EmbedingCache] = []
        for input_text in input:
            try:
                results.append(EmbedingCache(text=input_text, dim=self.model.dimension))
            except FileNotFoundError:
                # cache miss
                missed_inputs.append(input_text)
                continue

        if missed_inputs:
            assert self.model, "no embedding model specified"

            embedding_response = await self.client.embeddings.create(
                input=missed_inputs,
                model=self.model.id,
                dimensions=self.model.dimension,
                encoding_format="float"
            )

            for embedding_data, embedding_text in zip(embedding_response.data, missed_inputs):
                results.append(EmbedingCache(
                    text=embedding_text,
                    dim=self.model.dimension,
                    vec=np.array(embedding_data.embedding, dtype="float16"),
                ))

        return results[0] if was_unbatched else results

    def similarity(
        self,
        query: EmbedingCache,
        document: EmbeddedDocumentPiece,
        epsilon: float = 1e-6,
    ) -> float:
        assert epsilon != 0.0
        assert query.vec is not None
        assert document.vec is not None

        q_dot_docs = (query.vec * document.vec).sum(axis=-1)
        norm_coeff = np.linalg.norm(query.vec, axis=-1) * np.linalg.norm(document.vec, axis=-1)
        norm_coeff = np.clip(norm_coeff, a_min=epsilon, a_max=None)  # avoid devision by zero

        return float(q_dot_docs / norm_coeff)

    def search(self, query: EmbedingCache, best_n: int = 10):
        matches: list[DocumentPieceMatch] = []
        for document_piece in self.dataset:
            similarity_score = self.similarity(query, document_piece)
            matches.append(DocumentPieceMatch(
                text=document_piece.text,
                similarity_score=similarity_score,
                reference=document_piece.reference
            ))
        return sorted(matches, key=lambda x: x.similarity_score, reverse=True)[:best_n]
