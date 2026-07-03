from dataclasses import dataclass
from typing import Optional


@dataclass
class WikiMediaSearchResult:
    title: str
    snippet: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    pageid: Optional[str] = None