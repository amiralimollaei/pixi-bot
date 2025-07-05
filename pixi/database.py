from dataclasses import dataclass
from glob import glob
import asyncio
import hashlib
import json
import os
import re

import zstandard
import aiofiles

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
    snippet: str
    id: int
    num_matches: int
    source: str | None = None


class DocumentDataset:
    def __init__(self, data: dict[int, DatasetEntry] | None = None):
        if data is not None:
            assert isinstance(data, dict), f"expected data to be of type `set` but got `{data}`"
            for i, e in enumerate(data.values()):
                assert isinstance(
                    e, DatasetEntry), f"expetced all elements to be of type `DatasetEntry` but got `{e}` or type `{type(e)}`"
        self.data = data or dict()

    def add_entry(self, title: str, text: str, source: str | None = None):
        if text == None:
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

    async def search(self,
                     query: str,
                     skip_match: list[str] = [
                         "a", "an", "so", "is", "we", "us", "and", "the",
                         "they", "that", "this", "these", "those"
                     ]
                     ) -> list[QueryMatch]:
        matches = []
        _query = re.split(r"[^\w]", query.lower())
        for entry in self.data.values():
            _entry = re.split(r"([^\w])", entry.content)
            comparision = []
            for e in _entry:
                is_matched = False
                e_clean = re.sub(r"[^\w]", "", e).lower()
                if len(e) > 1 and e_clean in _query:
                    if e_clean not in skip_match:
                        is_matched = True

                comparision.append((e, is_matched))
            comparision = [(e, len(e) > 1 and re.sub(r"[^\w]", "", e).lower() in _query) for e in _entry]
            num_matches = 0
            snippet = []
            for i in range(len(comparision)):
                _e, matched = comparision[i]
                if matched:
                    comparision[i] = (f"<match>{_e}</match>", matched)
                    snippet.append("".join(map(lambda x: x[0], comparision[max(i-10, 0):i+10])))
                    num_matches += 1

            if num_matches != 0:
                matches.append(QueryMatch(
                    title=entry.title,
                    snippet="\n".join(snippet),
                    id=entry.id,
                    num_matches=num_matches,
                    source=entry.source
                ))

        return sorted(matches, key=lambda x: x.num_matches, reverse=True)


class DirectoryDatabase:
    def __init__(self, directory: str, dataset: DocumentDataset | None = None):
        self.directory = directory
        self.dataset = dataset or DocumentDataset()

    async def search(self, query: str) -> list[QueryMatch]:
        return await self.dataset.search(query=query)

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

    async def save(self):
        assert self.dataset, "dataset is not initialized, nothing to save"

        full_dir = os.path.join(BASE_DIR, self.directory)

        os.makedirs(full_dir, exist_ok=True)

        for entry in self.dataset.data.values():
            entry_hash = hashlib.sha256(
                (entry.content + entry.title + str(entry.source) + str(entry.id)).encode("utf-8")
            ).hexdigest()
            filepath = os.path.join(full_dir, f"{entry_hash}.zst")
            async with aiofiles.open(filepath, mode='wb') as f:
                json_data = json.dumps(dict(
                    title=entry.title,
                    content=entry.content,
                    id=entry.id,
                    source=entry.source or ""
                ), ensure_ascii=False)
                await f.write(zstandard.compress(json_data.encode("utf-8")))


if __name__ == "__main__":
    save = False

    if save:
        dataset = DocumentDataset()

        for file in glob("./pages-master/**/*.md"):
            content = open(file, "r", encoding="utf-8").read()
            dataset.add_entry(
                title=f"TechMCDocs ({file})",
                text=content,
                source="TechMCDocs"
            )

        print(asyncio.run(dataset.search("experience")))

        asyncio.run(DirectoryDatabase("TechMCDocs", dataset=dataset).save())

    async def main():
        database = await DirectoryDatabase.from_directory("TechMCDocs")
        matches = await database.search("update skipper")
        for match in matches:
            print(match)

    asyncio.run(main())
