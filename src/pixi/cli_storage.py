"""Storage option resolution and resource ownership for CLI commands."""

import os
from argparse import ArgumentParser
from contextlib import ExitStack


def resolve_storage_url(
    backend: str,
    url: str | None,
    prefix: str | None,
    parser: ArgumentParser,
    *,
    storage_option: str,
    url_option: str,
    prefix_option: str,
    missing_message: str,
) -> str | None:
    if url is None:
        if backend == "sql":
            url = os.getenv("DATABASE_URL")
        elif backend == "redis":
            url = os.getenv("REDIS_URL")
    if backend == "disk":
        if url is not None:
            parser.error(f"{url_option} requires {storage_option} sql or redis.")
    elif not url:
        parser.error(missing_message)
    if prefix is not None and backend != "redis":
        parser.error(f"{prefix_option} requires {storage_option} redis.")
    return url


def open_messages_storage(args, parser: ArgumentParser, resources: ExitStack):
    if args.messages_storage == "disk":
        return None
    if args.messages_storage == "sql":
        try:
            from pixi.storage.sql import MessagesSQLStorage
        except ImportError:
            parser.error("SQL message storage requires pip install 'pixi-bot[sql]'.")
        storage = MessagesSQLStorage(args.messages_storage_url)
    else:
        try:
            from pixi.storage.redis import MessagesRedisStorage
        except ImportError:
            parser.error(
                "Redis message storage requires pip install 'pixi-bot[redis]'."
            )
        storage = MessagesRedisStorage(
            args.messages_storage_url,
            key_prefix=args.redis_key_prefix
            if args.redis_key_prefix is not None
            else "pixi:messages:",
        )
    resources.callback(storage.close)
    return storage


def open_cache_storage(args, parser: ArgumentParser, resources: ExitStack):
    if args.cache_storage == "disk":
        return None
    if args.cache_storage == "sql":
        try:
            from pixi.caching.sql import CacheSQLStorage
        except ImportError:
            parser.error("SQL caching requires pip install 'pixi-bot[sql]'.")
        storage = CacheSQLStorage(args.cache_storage_url)
    else:
        try:
            from pixi.caching.redis import CacheRedisStorage
        except ImportError:
            parser.error("Redis caching requires pip install 'pixi-bot[redis]'.")
        storage = CacheRedisStorage(
            args.cache_storage_url,
            key_prefix=args.cache_redis_key_prefix
            if args.cache_redis_key_prefix is not None
            else "pixi:cache:",
        )
    resources.callback(storage.close)
    return storage
