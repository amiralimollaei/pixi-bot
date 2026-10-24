import asyncio
import logging
from types import CoroutineType
from typing import AsyncIterator, Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")


class AsyncStream(AsyncIterator[T], Generic[T]):
    def __init__(self, iterator: AsyncIterator[T]):
        self._iterator = iterator
        self._aiter = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
        return False

    def __aiter__(self):
        self._aiter = None
        return self

    async def __anext__(self) -> T:
        if self._aiter is None:
            self._aiter = self._iterator.__aiter__()
        return await self._aiter.__anext__()

    async def aclose(self):
        iterator = self._aiter or self._iterator
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()


class AsyncScheduler:
    """Schedules async tasks to execute after a delay."""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._tasks: dict[str, asyncio.Task] = {}

    async def _run_scheduled(self, id: str, delay: float, callback: Callable[[], Awaitable[None]]):
        try:
            await asyncio.sleep(delay)
            await callback()
        except asyncio.CancelledError:
            self.logger.info(f"Scheduled task '{id}' was cancelled.")
            raise
        except Exception:
            self.logger.exception(f"Scheduled task '{id}' raised an exception.")
        finally:
            if self._tasks.get(id) is asyncio.current_task():
                self._tasks.pop(id)

    def schedule(self, id: str, delay: float, callback: Callable[[], Awaitable[None]]) -> bool:
        id = str(id)
        if id in self._tasks:
            self.logger.warning(f"A task with id '{id}' is already scheduled.")
            return False
        task = asyncio.create_task(
            self._run_scheduled(id, delay, callback),
            name=f"scheduler-{id}",
        )
        self._tasks[id] = task
        return True

    def cancel(self, id: str) -> bool:
        id = str(id)
        task = self._tasks.pop(id, None)
        if task is None:
            self.logger.warning(f"No scheduled task with id '{id}' to cancel.")
            return False
        if not task.done():
            task.cancel()
            self.logger.info(f"Cancelled scheduled task '{id}'.")
            return True
        self.logger.info(f"Scheduled task '{id}' has already completed.")
        return True

    def cancel_all(self):
        for id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self.logger.info("All scheduled tasks have been cancelled.")

    async def aclose(self) -> None:
        """Cancel scheduled callbacks and wait for their cleanup."""
        tasks = tuple(self._tasks.values())
        self.cancel_all()
        await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def pending_count(self) -> int:
        return len(self._tasks)


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
            except asyncio.CancelledError:
                break

    async def add_to_queue(self, t: CoroutineType):
        await self._queue.put(t)

    async def __aenter__(self):
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
        try:
            if exc_type is None:
                await self._queue.join()
        finally:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            while not self._queue.empty():
                self._queue.get_nowait().close()
                self._queue.task_done()
