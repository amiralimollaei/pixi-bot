import dataclasses


@dataclasses.dataclass(frozen=True)
class MediaWikiConfig:
    url: str
    name: str
