from dataclasses import dataclass
from glob import glob
import hashlib
import json
import os
import re

import aiofiles
import zstandard

# constants

BASE_DIR = "datasets"


@dataclass
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


@dataclass
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