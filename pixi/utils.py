import asyncio
from enum import StrEnum
import importlib.resources
import logging
import os
from types import CoroutineType
from typing import IO

MODULE_PATH = importlib.resources.files(__package__) # pyright: ignore[reportArgumentType]
RESOURCES_PATH = str(MODULE_PATH / "resources")


class CoroutineQueueExecutor:
    def __init__(self, max_queue_size: int = 1000):
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.max_queue_size = max_queue_size
        self.tasks: list[CoroutineType] = []
        self.execute_lock = asyncio.Lock()
        self.execute_task = None

    async def __execute_queue(self):
        await self.execute_lock.acquire()
        while len(self.tasks) > 0:
            await self.tasks[0]
            del self.tasks[0]
        self.execute_lock.release()

    async def add_to_queue(self, t: CoroutineType):
        self.tasks.append(t)
        # if execute_lock is not acquired, we are not executing anything
        # in that case we should start executing the tasks
        if not self.execute_lock.locked():
            self.execute_task = asyncio.create_task(self.__execute_queue())

    async def __aenter__(self):
        self.execute_task = None
        if self.execute_lock.locked():
            self.execute_lock.release()

        if len(self.tasks) > 0:
            self.logger.warning(f"Corotine never avaited: {self.tasks}")

        self.tasks = []

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.execute_task:
            await self.execute_task

# helpers


def exists(value, allow_empty_string=False):
    if value is None:
        return False

    if isinstance(value, (int, float)):
        return True

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

def get_resource_path(resource_folder: str | None, filename) -> str:
    return os.path.join(resource_folder or RESOURCES_PATH, filename)

def open_resource(resource_folder: str | None, filename: str, mode: str) -> IO:
    return open(os.path.join(resource_folder or RESOURCES_PATH, filename), mode=mode, encoding="utf-8")