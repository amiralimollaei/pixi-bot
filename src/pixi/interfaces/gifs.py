from typing import Protocol

from pixi.model.gifs import GifSearchResult


class GifSearchAPI(Protocol):
    async def search(self, query: str) -> GifSearchResult:
        """Return GIFs with provider attribution; no match means an empty gifs tuple."""
        ...
