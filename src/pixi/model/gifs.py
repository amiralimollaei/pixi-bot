from dataclasses import dataclass


@dataclass(frozen=True)
class Gif:
    url: str
    id: str | None = None
    title: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    page_url: str | None = None


@dataclass(frozen=True)
class GifSearchResult:
    results: tuple[Gif, ...]
    attribution: str
