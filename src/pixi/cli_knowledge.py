"""Knowledge storage options shared by bot startup and offline imports."""

from argparse import ArgumentParser, Namespace
from contextlib import ExitStack
import os
from pathlib import Path

from .interfaces.knowledge import KnowledgeStorage


def add_storage_arguments(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--knowledge-storage", choices=("disk", "sql", "redis"), default="disk",
        help="Knowledge-base backend (default: disk under --pixi-directory).",
    )
    parser.add_argument(
        "--knowledge-storage-url", metavar="URL",
        help="Knowledge SQLAlchemy or Redis URL; defaults to DATABASE_URL for sql, REDIS_URL for redis.",
    )
    parser.add_argument(
        "--knowledge-redis-key-prefix", metavar="PREFIX",
        help="Knowledge Redis namespace (default: pixi:datasets:); requires --knowledge-storage redis.",
    )


def resolve_storage_options(args: Namespace, parser: ArgumentParser) -> None:
    if args.knowledge_storage_url is None:
        if args.knowledge_storage == "sql":
            args.knowledge_storage_url = os.getenv("DATABASE_URL")
        elif args.knowledge_storage == "redis":
            args.knowledge_storage_url = os.getenv("REDIS_URL")
    if args.knowledge_storage == "disk":
        if args.knowledge_storage_url is not None:
            parser.error("--knowledge-storage-url requires --knowledge-storage sql or redis.")
    elif not args.knowledge_storage_url:
        parser.error("SQL/Redis knowledge storage requires --knowledge-storage-url or DATABASE_URL/REDIS_URL.")
    if args.knowledge_redis_key_prefix is not None and args.knowledge_storage != "redis":
        parser.error("--knowledge-redis-key-prefix requires --knowledge-storage redis.")


def open_storage(args: Namespace, parser: ArgumentParser, resources: ExitStack) -> KnowledgeStorage:
    if args.knowledge_storage == "disk":
        from .storage.knowledge_disk import KnowledgeDiskStorage

        return KnowledgeDiskStorage(Path(args.pixi_directory).expanduser() / "datasets")
    if args.knowledge_storage == "sql":
        try:
            from .storage.sql import KnowledgeSQLStorage
        except ImportError:
            parser.error("SQL knowledge storage requires pip install 'pixi-bot[sql]'.")
        storage = KnowledgeSQLStorage(args.knowledge_storage_url)
    else:
        try:
            from .storage.redis import KnowledgeRedisStorage
        except ImportError:
            parser.error("Redis knowledge storage requires pip install 'pixi-bot[redis]'.")
        storage = KnowledgeRedisStorage(
            args.knowledge_storage_url,
            key_prefix=(args.knowledge_redis_key_prefix
                        if args.knowledge_redis_key_prefix is not None else "pixi:datasets:"),
        )
    resources.callback(storage.close)
    return storage
