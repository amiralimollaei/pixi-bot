import asyncio
from enum import StrEnum
import logging
import os
from pathlib import Path
from types import CoroutineType
from typing import IO, Sequence


class CoroutineQueueExecutor:
    def __init__(self, max_queue_size: int = 1000):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.max_queue_size = max_queue_size
        self._queue: asyncio.Queue[CoroutineType] = asyncio.Queue(maxsize=max_queue_size)

    async def _worker(self):
        while True:
            try:
                coro = await self._queue.get()
                try:
                    await coro
                except Exception:
                    self.logger.exception("Coroutine resulted in an error")
                finally:
                    self._queue.task_done()
            except (asyncio.CancelledError, asyncio.QueueShutDown):
                break

    async def add_to_queue(self, t: CoroutineType):
        await self._queue.put(t)

    async def __aenter__(self):
        # drain any tasks left over from a previous use
        if not self._queue.empty():
            remaining = []
            while not self._queue.empty():
                try:
                    remaining.append(self._queue.get_nowait())
                    self._queue.task_done()
                except asyncio.QueueEmpty:
                    break
            self.logger.warning(f"Coroutine never awaited: {remaining}")

        self._worker_task = asyncio.create_task(self._worker())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._queue.join()
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass


# helpers


def exists(value, allow_empty_string=False):
    if value is None:
        return False
    
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value != "" or (value == "" and allow_empty_string)

    if isinstance(value, (list, tuple, dict)):
        return len(value) != 0

    return True


def load_dotenv():
    # load environment variables
    try:
        import dotenv  # pyright: ignore[reportMissingImports]
    except ImportError:
        logging.warning("dotenv is not installed, install it using `pip install dotenv`")
    else:
        dotenv.load_dotenv()


# modified from https://stackoverflow.com/a/76636817
def format_time_ago(delta: float, min_count: int = 3, max_lenght: int = 2) -> str:
    """Return time difference as human-readable string"""

    periods = (
        ("year", 31536000),
        ("month", 2592000),
        ("week", 604800),
        ("day", 86400),
        ("hour", 3600),
        ("minute", 60),
        ("second", 1),
    )

    fmt_list = []
    for period, seconds_each in periods:
        if delta >= seconds_each:
            how_many = int(delta / seconds_each)
            if how_many >= min_count:
                fmt_list.append(f"{how_many} {period}{'s' if how_many >= 2 else ''}")
                if len(fmt_list) >= max_lenght:
                    break

                delta -= seconds_each * how_many

    if fmt_list:
        return " and ".join(fmt_list) + " ago"

    return "just now"  # less than a second ago


class Ansi(StrEnum):
    END = '\33[0m'
    BOLD = '\33[1m'
    ITALIC = '\33[3m'
    URL = '\33[4m'
    BLINK = '\33[5m'
    BLINK2 = '\33[6m'
    SELECTED = '\33[7m'

    BLACK = '\33[30m'
    RED = '\33[31m'
    GREEN = '\33[32m'
    YELLOW = '\33[33m'
    BLUE = '\33[34m'
    VIOLET = '\33[35m'
    BEIGE = '\33[36m'
    WHITE = '\33[37m'

    BLACKBG = '\33[40m'
    REDBG = '\33[41m'
    GREENBG = '\33[42m'
    YELLOWBG = '\33[43m'
    BLUEBG = '\33[44m'
    VIOLETBG = '\33[45m'
    BEIGEBG = '\33[46m'
    WHITEBG = '\33[47m'

    GREY = '\33[90m'
    RED2 = '\33[91m'
    GREEN2 = '\33[92m'
    YELLOW2 = '\33[93m'
    BLUE2 = '\33[94m'
    VIOLET2 = '\33[95m'
    BEIGE2 = '\33[96m'
    WHITE2 = '\33[97m'

    GREYBG = '\33[100m'
    REDBG2 = '\33[101m'
    GREENBG2 = '\33[102m'
    YELLOWBG2 = '\33[103m'
    BLUEBG2 = '\33[104m'
    VIOLETBG2 = '\33[105m'
    BEIGEBG2 = '\33[106m'
    WHITEBG2 = '\33[107m'

def clean_dict(d: dict):
    final_dict = {}
    for k, v in d.items():
        if v is None:
            continue
        elif isinstance(v, dict):
            if len(v) == 0:
                continue
            v = clean_dict(v)
        elif isinstance(v, Sequence):
            if len(v) == 0:
                continue
            if not isinstance(v, str): # other than strings, we every other sequence is a nested dynamic type
                v = [(clean_dict(e) if isinstance(e, dict) else e) for e in v]
        final_dict[k] = v
    return final_dict