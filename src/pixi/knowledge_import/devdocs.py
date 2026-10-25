"""Read the page database and optional indexes of a local DevDocs bundle."""

import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote, urljoin

from ..model.storage.document import DocumentMeta
from .html import html_to_text


def _read_object(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _read_titles(path: Path) -> dict[str, str]:
    index = _read_object(path)
    entries = index.get("entries")
    if not isinstance(entries, list):
        raise ValueError("DevDocs index.json must contain an entries array")
    if "types" in index:
        types = index["types"]
        if not isinstance(types, list):
            raise ValueError("DevDocs index types must be an array")
        for item in types:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError("DevDocs index types must be objects with string names")
            if "count" in item and (type(item["count"]) is not int or item["count"] < 0):
                raise ValueError("DevDocs index type counts must be nonnegative integers")
            if "slug" in item and not isinstance(item["slug"], str):
                raise ValueError("DevDocs index type slugs must be strings")
    titles: dict[str, str] = {}
    page_titles: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("DevDocs index entries must be objects")
        name, entry_path = entry.get("name"), entry.get("path")
        if not isinstance(name, str) or not name.strip() or not isinstance(entry_path, str):
            raise ValueError("DevDocs index entries require a nonempty name and a string path")
        if "type" in entry and entry["type"] is not None and not isinstance(entry["type"], str):
            raise ValueError("DevDocs index entry types must be strings or null")
        page_path, separator, _ = entry_path.partition("#")
        titles.setdefault(page_path, name)
        if not separator:
            page_titles.setdefault(page_path, name)
    titles.update(page_titles)
    return titles


def _read_home(path: Path) -> str | None:
    metadata = _read_object(path)
    for key in ("name", "slug", "type", "version", "release"):
        if key in metadata and metadata[key] is not None and not isinstance(metadata[key], str):
            raise ValueError(f"DevDocs metadata {key} must be a string or null")
    for key in ("mtime", "db_size"):
        if key in metadata and (type(metadata[key]) is not int or metadata[key] < 0):
            raise ValueError(f"DevDocs metadata {key} must be a nonnegative integer")
    if "links" not in metadata:
        return None
    links = metadata["links"]
    if not isinstance(links, dict) or any(not isinstance(value, str) for value in links.values()):
        raise ValueError("DevDocs metadata links must be an object of URL strings")
    home = links.get("home")
    return home if home else None


class DevDocsImporter:
    def read_documents(self, path: Path) -> Iterator[DocumentMeta]:
        """Import each db.json page once, using optional index.json and meta.json.
    
        IDs are one-based positions in the sorted database paths. Index anchor
        entries supply fallback titles, never extra copies of a database page.
        """
        database_path = path / "db.json" if path.is_dir() else path
        if database_path.name != "db.json":
            raise ValueError("DevDocs source must be db.json or a directory containing db.json")
        pages: dict[str, str] = _read_object(database_path)
        if any(not page_path or not isinstance(html, str) for page_path, html in pages.items()):
            raise ValueError("DevDocs db.json must map nonempty page paths to HTML strings")
        index_path = database_path.with_name("index.json")
        metadata_path = database_path.with_name("meta.json")
        titles = _read_titles(index_path) if index_path.exists() else {}
        home = _read_home(metadata_path) if metadata_path.exists() else None
        local_source = database_path.resolve().as_uri()
        for identifier, page_path in enumerate(sorted(pages), start=1):
            content = html_to_text(pages[page_path])
            if not content.strip():
                continue
            source = (
                urljoin(home.rstrip("/") + "/", quote(page_path, safe="/"))
                if home
                else f"{local_source}#{quote(page_path, safe='')}"
            )
            yield DocumentMeta(
                title=titles.get(page_path, page_path),
                content=content,
                id=identifier,
                source=source,
            )
