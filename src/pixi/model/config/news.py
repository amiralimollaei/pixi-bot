from dataclasses import dataclass


@dataclass(frozen=True)
class NewsConfig:
    feed_url: str
    interval_sec: int = 1
    probability: float = 0.1