import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from . import HTTPAPI

# helpers

def _get_text(parent, tag: str) -> Optional[str]:
    el = parent.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


# model

@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    link: str
    published: Optional[str] = None


# main

class AsyncRSSAPI(HTTPAPI):
    """Fetches news headlines from an RSS/Atom feed URL."""

    def __init__(self, url: str, api_key: Optional[str] = None):
        super().__init__(base=url, api_key=api_key, api_key_env_var=None)

    async def request_xml(self, url: str, data: Optional[dict] = None):
        text = await self.request_raw(url=url, data=data)
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        
        return root

    async def fetch(self, max_items: int = 10) -> list[NewsItem]:
        """Fetch and parse an RSS/Atom feed, returning up to `max_items` headlines."""
        root = await self.request_xml("/")
        if not root:
            return []

        items: list[NewsItem] = []

        # RSS feed structure: <rss><channel><item>...</item></channel></rss>
        rss_channel = root.find("channel")
        if rss_channel is not None:
            for item in rss_channel.findall("item"):
                title = _get_text(item, "title")
                description = _get_text(item, "description")
                link = _get_text(item, "link")
                pub_date = _get_text(item, "pubDate")
                if title:
                    items.append(NewsItem(
                        title=title,
                        summary=_strip_html(description or ""),
                        link=link or "",
                        published=pub_date,
                    ))

        # Atom feed structure: <feed><entry>...</entry></feed>
        atom_ns = "{http://www.w3.org/2005/Atom}"
        if not items and root.tag == f"{atom_ns}feed":
            for entry in root.findall(f"{atom_ns}entry"):
                title = _get_text(entry, f"{atom_ns}title")
                summary = _get_text(entry, f"{atom_ns}summary") or _get_text(entry, f"{atom_ns}content")
                link_el = entry.find(f"{atom_ns}link")
                link = link_el.get("href", "") if link_el is not None else ""
                published = _get_text(entry, f"{atom_ns}published") or _get_text(entry, f"{atom_ns}updated")
                if title:
                    items.append(NewsItem(
                        title=title,
                        summary=_strip_html(summary or ""),
                        link=link,
                        published=published,
                    ))


        return items[:max_items]