import dataclasses


@dataclasses.dataclass
class MediaWikiConfig:
    url: str
    name: str