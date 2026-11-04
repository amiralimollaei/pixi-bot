import re

from pixi.interfaces.knowledge import KnowledgeStorage
from pixi.model.search.document import QueryMatch
from pixi.model.storage.document import DocumentMeta


class DocumentCollection:
    def __init__(self, data: dict[int, DocumentMeta] | None = None):
        if data:
            assert isinstance(data, dict), (
                f"expected data to be of type `dict` but got `{data}`"
            )
            for e in data.values():
                if isinstance(e, DocumentMeta):
                    continue
                raise TypeError(
                    f"expected all elements to be DocumentMeta instances, but got `{type(e)}`"
                )
        self.data = data or dict()

    def add_document(self, title: str, text: str, source: str | None = None):
        text = text.strip(" \n\r\t")
        if not text:
            return

        entry = DocumentMeta(
            title=title, content=text, id=max(self.data, default=-1) + 1, source=source
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

        # 2. Iterate through each document in the collection.
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

            all_matches.add(
                QueryMatch(
                    title=entry.title,
                    id=entry.id,
                    source=entry.source,
                    num_matches=num_matches,
                    match_score=(num_matches / len(content_parts)) * 100,
                )
            )

        # Break relevance ties by document ID so reloads preserve search ordering.
        return sorted(all_matches, key=lambda m: (-m.num_matches, m.id))[:best_n]


class KnowledgeBase:
    def __init__(
        self,
        name: str,
        *,
        storage: KnowledgeStorage,
        documents: DocumentCollection | None = None,
    ):
        self.name = name
        self.storage = storage
        self.documents = documents if documents is not None else DocumentCollection()

    async def search(self, query: str, best_n: int = 10) -> list[QueryMatch]:
        return await self.documents.search(query=query, best_n=best_n)

    async def get_document(self, id: int) -> DocumentMeta:
        entry = self.documents.get(id=id)
        if entry is None:
            raise KeyError(f"No entry found with {id=}")
        return entry

    @classmethod
    def from_storage(cls, name: str, storage: KnowledgeStorage):
        documents = storage.load(name)
        collection = DocumentCollection(
            {document.id: document for document in documents}
        )
        return cls(name, storage=storage, documents=collection)

    def clear(self) -> None:
        self.storage.delete(self.name)
        self.documents.data.clear()

    def save(self) -> None:
        self.storage.save(self.name, list(self.documents.data.values()))
