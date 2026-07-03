import hashlib
import json
import os
import re
from glob import glob

import zstandard

from ..model.search.document import QueryMatch
from ..model.storage.document import DocumentMeta
from .paths import PixiPaths


class DocumentDataset:
    def __init__(self, data: dict[int, DocumentMeta] | None = None):
        if data:
            assert isinstance(data, dict), f"expected data to be of type `dict` but got `{data}`"
            for e in data.values():
                if isinstance(e, DocumentMeta):
                    continue
                raise TypeError(f"expetced all elements to be of type `DatasetEntry` but got `{type(e)}`")
        self.data = data or dict()

    def add_entry(self, title: str, text: str, source: str | None = None):
        text = text.strip(" \n\r\t")
        if not text:
            return

        entry = DocumentMeta(
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

    async def get_entry(self, id: int) -> DocumentMeta:
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
                entry = DocumentMeta(
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

    def get_entry_hash(self, entry: DocumentMeta):
        return hashlib.sha256(
            (entry.content + entry.title + str(entry.source) + str(entry.id)).encode("utf-8")
        )
