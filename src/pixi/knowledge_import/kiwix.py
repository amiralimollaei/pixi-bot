"""Read local ZIM archives with the optional python-libzim 3.x bindings."""

from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from urllib.parse import quote

from ..model.storage.document import DocumentMeta
from .html import html_to_text


class KiwixImporter:
    def read_documents(self, path: Path) -> Iterator[DocumentMeta]:
        """Yield HTML/plain-text articles in archive order, without following redirects.
    
        IDs are the archive's stable directory indexes. Sources are local archive
        file URIs with the entry path as a fragment; no original URL is guessed.
        Text must decode using its declared MIME charset, or UTF-8 by default.
        """
        if not path.is_file():
            raise ValueError(f"Kiwix source must be a local ZIM file: {path}")
    
        try:
            from libzim import reader
        except ImportError as exc:
            raise RuntimeError(
                "Kiwix import requires libzim; install it with "
                "pip install 'pixi-bot[kiwix]'."
            ) from exc
    
        source_uri = path.resolve().as_uri()
        entry_id = None
        try:
            archive = reader.Archive(path)
            modern_namespaces = archive.has_new_namespace_scheme
            # entry_count counts user entries, but IDs index the complete directory.
            # Released libzim 3.x exposes enumeration as _get_entry_by_id.
            for entry_id in range(archive.all_entry_count):
                entry = archive._get_entry_by_id(entry_id)
                if entry.is_redirect:
                    continue
                entry_path = entry.path
                if modern_namespaces:
                    # The C/ prefix is stripped by Entry.path, including for entries
                    # in M/ and X/. Lookup only returns C/ content. Compare indexes
                    # because metadata may share its path with a genuine article.
                    if not archive.has_entry_by_path(entry_path):
                        continue
                    user_entry = archive.get_entry_by_path(entry_path)
                    if user_entry._index != entry_id:
                        continue
                elif not entry_path.startswith("A/"):
                    continue
    
                item = entry.get_item()
                mimetype = item.mimetype
                media_type = mimetype.split(";", 1)[0].strip().lower()
                if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    continue
    
                # Inspect MIME metadata before accessing content: images, indexes,
                # and other binary assets must never be copied into Python bytes.
                mime = Message()
                mime["content-type"] = mimetype
                charset = mime.get_content_charset() or "utf-8"
                text = bytes(item.content).decode(charset)
                content = text if media_type == "text/plain" else html_to_text(text)
                if not content.strip():
                    continue
                yield DocumentMeta(
                    title=entry.title,
                    content=content,
                    id=entry_id,
                    source=f"{source_uri}#{quote(entry_path, safe='/')}",
                )
        except (RuntimeError, OSError, ValueError, LookupError) as exc:
            location = "" if entry_id is None else f" at entry {entry_id}"
            raise ValueError(f"Cannot read ZIM archive {path}{location}: {exc}") from exc
