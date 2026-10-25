"""Read local MediaWiki XML exports, retaining their original wikitext."""

import bz2
import gzip
import lzma
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import iterparse

from ..model.storage.document import DocumentMeta


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _page_document(
    page: Element, path: Path, article_prefix: str | None
) -> DocumentMeta | None:
    fields = {
        _local_name(child.tag): child
        for child in page
        if _local_name(child.tag) != "revision"
    }
    title = fields.get("title")
    page_id = fields.get("id")
    if title is None or not title.text or page_id is None or not page_id.text:
        raise ValueError("MediaWiki page is missing its title or page ID")
    try:
        identifier = int(page_id.text)
        namespace = int(fields["ns"].text or "") if "ns" in fields else 0
    except ValueError as error:
        raise ValueError("MediaWiki page ID and namespace must be integers") from error
    if identifier < 0:
        raise ValueError("MediaWiki page ID must be nonnegative")
    if namespace != 0 or "redirect" in fields:
        return None

    # History exports normally order revisions chronologically. Timestamps also
    # select the latest revision when a producer emits them in another order.
    latest: Element | None = None
    latest_timestamp = ""
    for revision in page:
        if _local_name(revision.tag) != "revision":
            continue
        timestamp = next(
            (child.text or "" for child in revision if _local_name(child.tag) == "timestamp"),
            "",
        )
        if latest is None or timestamp >= latest_timestamp:
            latest = revision
            latest_timestamp = timestamp
    if latest is None or "deleted" in latest.attrib:
        return None
    text = next((child for child in latest if _local_name(child.tag) == "text"), None)
    if text is None or "deleted" in text.attrib or not (text.text or "").strip():
        return None
    source = (
        article_prefix + quote(title.text.replace(" ", "_"), safe="/")
        if article_prefix
        else f"{path.resolve().as_uri()}#page={identifier}"
    )
    return DocumentMeta(title=title.text, content=text.text or "", id=identifier, source=source)


class MediaWikiImporter:
    def read_documents(self, path: Path) -> Iterator[DocumentMeta]:
        """Read XML, XML.gz, XML.bz2, or XML.xz without retaining completed pages.
    
        Only main-namespace, nonredirect pages are imported. Latest revision text is
        kept as wikitext; deleted or empty latest revisions are not imported.
        """
        opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}.get(path.suffix.lower(), open)
        article_prefix = None
        seen_ids: set[int] = set()
        with opener(path, "rb") as stream:
            events = iterparse(stream, events=("start", "end"), forbid_dtd=True)
            try:
                _, root = next(events)
            except StopIteration as error:
                raise ValueError("MediaWiki XML is empty") from error
            if _local_name(root.tag) != "mediawiki" or (
                root.tag.startswith("{")
                and not root.tag.startswith("{http://www.mediawiki.org/xml/export-")
            ):
                raise ValueError("Expected a MediaWiki XML export")
            depth = 1
            for event, element in events:
                if event == "start":
                    depth += 1
                    continue
                if depth == 2:
                    name = _local_name(element.tag)
                    if name == "siteinfo":
                        base = next(
                            (child.text for child in element if _local_name(child.tag) == "base"),
                            None,
                        )
                        if base:
                            parsed = urlsplit(base)
                            if parsed.scheme in {"http", "https"} and parsed.netloc:
                                article_prefix = base.rsplit("/", 1)[0] + "/"
                    elif name == "page":
                        document = _page_document(element, path, article_prefix)
                        if document is not None:
                            if document.id in seen_ids:
                                raise ValueError(f"Duplicate MediaWiki page ID: {document.id}")
                            seen_ids.add(document.id)
                            yield document
                    else:
                        raise ValueError(f"Unexpected MediaWiki export element: {name}")
                    element.clear()
                    root.clear()
                depth -= 1
