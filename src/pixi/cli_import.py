"""Offline knowledge-base imports; deliberately independent of bot startup."""

import argparse
from contextlib import ExitStack
from lzma import LZMAError
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException

from .cli_knowledge import add_storage_arguments, open_storage, resolve_storage_options
from .knowledge_import import IMPORTERS


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="pixi-cli import-knowledge",
        description="Import a local documentation dump into a named knowledge base.",
    )
    parser.add_argument("name", help="Destination knowledge-base name.")
    parser.add_argument("source", type=Path, help="Local dump file, or DevDocs directory.")
    parser.add_argument(
        "--format", required=True, choices=IMPORTERS,
        help="Importer used to read the local source.",
    )
    parser.add_argument(
        "--pixi-directory", "-pd", default="~/.pixi/",
        help="Pixi data root (default: ~/.pixi/).",
    )
    parser.add_argument(
        "--replace", action="store_true",
        help="Replace an existing snapshot, removing documents absent from this import.",
    )
    add_storage_arguments(parser)
    args = parser.parse_args(argv)
    resolve_storage_options(args, parser)
    if not args.name or args.name in {".", ".."} or any(c in args.name for c in ("/", "\\", "\0")):
        parser.error("knowledge-base names must be nonempty single path components")
    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"source does not exist: {source}")

    try:
        with ExitStack() as resources:
            storage = open_storage(args, parser, resources)
            if not args.replace and storage.load(args.name):
                parser.error(f"knowledge base {args.name!r} already exists; use --replace to overwrite it")
            documents = list(IMPORTERS[args.format].read_documents(source))
            if not documents:
                parser.error("source contains no importable documents; existing knowledge was not changed")
            storage.save(args.name, documents)
    except (
        OSError, EOFError, LZMAError, ParseError, DefusedXmlException,
        ValueError, TypeError, RuntimeError, ImportError,
    ) as exc:
        parser.error(str(exc))
    print(f"Imported {len(documents)} documents into knowledge base {args.name!r} ({args.knowledge_storage}).")
