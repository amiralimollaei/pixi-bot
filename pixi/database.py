import dataclasses
from glob import glob
import hashlib
import json
import os
import re

import aiofiles
import httpx
import numpy as np
import openai
import zstandard

from .caching import EmbedingCache
from .config import OpenAIAuthConfig, OpenAIEmbeddingModelConfig

# constants

BASE_DIR = "datasets"


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
    async def from_directory(cls, directory: str):
        assert directory

        full_dir = os.path.join(BASE_DIR, directory)

        if not os.path.isdir(full_dir):
            dataset = DocumentDataset()
            return cls(directory=directory, dataset=dataset)

        data = dict()
        for file in glob(os.path.join(full_dir, "*.zst")):
            async with aiofiles.open(file, mode='rb') as f:
                json_data = zstandard.decompress(await f.read())
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

    def clear(self):
        full_dir = os.path.join(BASE_DIR, self.directory)
        for file in glob(os.path.join(full_dir, "*.zst")):
            if os.path.isfile(file):
                os.remove(file)

    async def save(self):
        assert self.dataset, "dataset is not initialized, nothing to save"

        full_dir = os.path.join(BASE_DIR, self.directory)

        os.makedirs(full_dir, exist_ok=True)

        for entry in self.dataset.data.values():
            entry_hash = self.get_entry_hash(entry).hexdigest()
            filepath = os.path.join(full_dir, f"{entry_hash}.zst")
            async with aiofiles.open(filepath, mode='wb') as f:
                json_data = json.dumps(dict(
                    title=entry.title,
                    content=entry.content,
                    id=entry.id,
                    source=entry.source or ""
                ), ensure_ascii=False)
                await f.write(zstandard.compress(json_data.encode("utf-8")))

    def get_entry_hash(self, entry: DatasetEntry):
        return hashlib.sha256(
            (entry.content + entry.title + str(entry.source) + str(entry.id)).encode("utf-8")
        )


class SentenceTokenizer:
    """This class provides functions for extracting sentences from text."""

    def __init__(self: "SentenceTokenizer") -> None:
        self.pattern = re.compile(r"([!.?⸮؟]+)[ \n]+")

    def tokenize(self: "SentenceTokenizer", text: str) -> list[str]:
        """Splits the input text into its component sentences.

        Examples:
            >>> tokenizer = SentenceTokenizer()
            >>> tokenizer.tokenize('Splitting is simple. Almost, anyway!')
            ['Splitting is simple.', 'Almost, anyway!']

        Args:
            text: The text whose sentences should be extracted.

        Returns:
            A list of extracted sentences.
        """
        text = self.pattern.sub(r"\1\n\n", text)
        return [
            sentence.replace("\n", " ").strip()
            for sentence in text.split("\n\n")
            if sentence.strip()
        ]


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


class AsyncEmbeddingDatabase:
    def __init__(self, auth: OpenAIAuthConfig, model: OpenAIEmbeddingModelConfig):
        self.auth = auth
        self.model = model

        self.sent_tokenizer = SentenceTokenizer()

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

        paragraph level splitting algorithm:
          - split the text into paragraphs and for each paragraph:
          - if the paragraph's length is between `min_chunk_size` and `max_chunk_size`, yield the paragraph
          - if the paragraph's length is less than `min_chunk_size` add it to the start of the next paragraph
          - if the paragraph's length is more than `max_chunk_size` split it using `sentence_chunk_split`,
          and add the remainder to the next paragraph

        params:
            text: (str) the full text of the document to be porcessed
            name: (str) the name of the document used for referencing
            id: (int) the id of the document used for referencing

        returns:
            None
        """

        text = text.strip(" \n\r\t")

        chunks = []
        current_chunk = ""
        if self.model.sentence_level:
            chunks, current_chunk = self.sentence_chunk_split(text)
        else:
            for paragraph in PARAGRAPH_SPLIT.split(text):
                current_chunk += paragraph + "\n\n"
                if self.model.min_chunk_size < len(current_chunk) < self.model.max_chunk_size:
                    chunks.append(current_chunk)
                    current_chunk = ""
                elif len(current_chunk) > self.model.max_chunk_size:
                    new_chunks, current_chunk = self.sentence_chunk_split(current_chunk)
                    if new_chunks:
                        chunks += new_chunks
                if len(current_chunk) > self.model.min_chunk_size:
                    chunks.append(current_chunk)
                    current_chunk = ""
        current_chunk = current_chunk.strip(" \n\r\t")
        if current_chunk:
            chunks.append(current_chunk)

        await self.add_document_piece(
            chunks,
            reference=EmbeddedDocumentReference(
                name=name,
                id=id
            )
        )

    def sentence_chunk_split(self, current_chunk: str) -> tuple[list[str], str]:
        chunks: list[str] = []
        sentences = []
        for line in current_chunk.split("\n"):
            if not line:
                continue
            line_sentences = self.sent_tokenizer.tokenize(line)
            if not line_sentences:
                continue
            line_sentences[-1] = line_sentences[-1] + "\n"
            sentences += line_sentences
        temp_chunk: str = ""
        for sentence in sentences:
            temp_chunk += sentence
            if not temp_chunk.endswith((" ", "\n", "\n\r", "\t")):
                temp_chunk += " "
            while len(temp_chunk) > self.model.max_chunk_size:
                chunks.append(temp_chunk[:self.model.max_chunk_size])
                temp_chunk = temp_chunk[self.model.max_chunk_size:]
            if len(temp_chunk) > self.model.min_chunk_size:
                chunks.append(temp_chunk)
                temp_chunk = ""
        current_chunk = temp_chunk
        return chunks, current_chunk

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
