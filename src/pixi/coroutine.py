import asyncio
import logging
from types import CoroutineType
from typing import Awaitable, Callable


class AsyncScheduler:
    """Schedules async tasks to execute after a delay.

    Usage:
        scheduler = AsyncScheduler()
        scheduler.schedule("reminder_1", 7200, lambda: some_async_func())
        scheduler.cancel("reminder_1")
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._tasks: dict[str, asyncio.Task] = {}

    async def _run_scheduled(self, id: str, delay: float, callback: Callable[[], Awaitable[None]]):
        """Internal coroutine that waits for `delay` seconds then calls `callback`."""
        try:
            await asyncio.sleep(delay)
            await callback()
        except asyncio.CancelledError:
            self.logger.info(f"Scheduled task '{id}' was cancelled.")
            raise
        except Exception:
            self.logger.exception(f"Scheduled task '{id}' raised an exception.")
        finally:
            self._tasks.pop(id, None)

    def schedule(self, id: str, delay: float, callback: Callable[[], Awaitable[None]]) -> bool:
        """Schedule a callback to run after `delay` seconds.

        Returns True on success, False if a task with this ID already exists.
        """
        id = str(id)
        if id in self._tasks:
            self.logger.warning(f"A task with id '{id}' is already scheduled.")
            return False

        task = asyncio.create_task(
            self._run_scheduled(id, delay, callback),
            name=f"scheduler-{id}"
        )
        self._tasks[id] = task
        return True

    def cancel(self, id: str) -> bool:
        """Cancel a scheduled task by its ID.

        Returns True if the task was found and cancelled, False otherwise.
        """
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
        """Cancel all pending scheduled tasks."""
        for id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self.logger.info("All scheduled tasks have been cancelled.")

    @property
    def pending_count(self) -> int:
        """Number of tasks waiting to run."""
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
