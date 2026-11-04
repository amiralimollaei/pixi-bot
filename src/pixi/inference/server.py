import asyncio
import socket
import tempfile
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator, Generic, TypeVar
from urllib.error import URLError
from urllib.request import urlopen

from pixi.model.config.llama import LlamaServerConfig

ClientT = TypeVar("ClientT")


class LlamaServer(ABC, Generic[ClientT]):
    """Lazily manage a local llama-server process."""

    def __init__(self, model: LlamaServerConfig):
        self.model = model
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._client: ClientT | None = None
        self._log = None
        self._port: int | None = None
        self._timer: asyncio.Task[None] | None = None
        self._generation = 0
        self._closed = False

    @abstractmethod
    def _create_client(self, port: int) -> ClientT:
        """Create this adapter's OpenAI-compatible client for a ready server."""
        raise NotImplementedError

    @abstractmethod
    def _server_arguments(self) -> tuple[str, ...]:
        """Return server-mode arguments specific to this adapter."""
        raise NotImplementedError

    def _binary_help(self) -> str:
        return "Install llama.cpp and set the llama-server binary option if needed."

    @asynccontextmanager
    async def _request(self, closed_message: str) -> AsyncGenerator[ClientT, None]:
        async with self._lock:
            if self._closed:
                raise RuntimeError(closed_message)
            self._cancel_idle_timer()
            try:
                await self._ensure_started()
                assert self._client is not None
                yield self._client
            except BaseException:
                await self._stop_server()
                raise
            else:
                self._arm_idle_timer()

    def _cancel_idle_timer(self) -> None:
        self._generation += 1
        task, self._timer = self._timer, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _arm_idle_timer(self) -> None:
        self._generation += 1
        generation = self._generation
        self._timer = asyncio.create_task(self._stop_when_idle(generation))

    async def _stop_when_idle(self, generation: int) -> None:
        try:
            await asyncio.sleep(max(0.0, self.model.idle_timeout))
            async with self._lock:
                if generation == self._generation and not self._closed:
                    self._timer = None
                    await self._stop_server()
        except asyncio.CancelledError:
            pass

    async def _ensure_started(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            return
        if process is not None:
            raise RuntimeError(self._server_failure("llama-server exited unexpectedly"))

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self._port = port
        self._log = tempfile.TemporaryFile(mode="w+b")
        args = [self.model.binary, "--hf-repo", self.model.hf_repo]
        if self.model.hf_file:
            args.extend(("--hf-file", self.model.hf_file))
        args.extend(self._server_arguments())
        args.extend(
            (
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ctx-size",
                str(self.model.max_context),
                "--alias",
                self.model.hf_repo,
                "--no-warmup",
            )
        )
        try:
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    *args,
                    stdout=self._log,
                    stderr=asyncio.subprocess.STDOUT,
                )
            )
            try:
                self._process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                self._process = await spawn
                raise
        except FileNotFoundError as exc:
            await self._stop_server()
            raise RuntimeError(
                f"Could not find llama-server executable {self.model.binary!r}. "
                f"{self._binary_help()}"
            ) from exc
        except BaseException:
            await self._stop_server()
            raise

        deadline = time.monotonic() + self.model.startup_timeout
        health_url = f"http://127.0.0.1:{port}/health"
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.returncode is not None:
                raise RuntimeError(
                    self._server_failure("llama-server exited before becoming ready")
                )
            try:
                ready = await asyncio.to_thread(self._health_check, health_url)
            except (OSError, URLError, TimeoutError):
                ready = False
            if ready:
                self._client = self._create_client(port)
                return
            await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        raise RuntimeError(
            self._server_failure("Timed out waiting for llama-server readiness")
        )

    @staticmethod
    def _health_check(url: str) -> bool:
        with urlopen(url, timeout=1.0) as response:
            return response.status == 200

    def _server_failure(self, message: str) -> str:
        detail = ""
        if self._log is not None:
            try:
                self._log.flush()
                self._log.seek(0, 2)
                self._log.seek(max(0, self._log.tell() - 65536))
                detail = self._log.read().decode("utf-8", errors="replace").strip()
            except OSError:
                pass
        return f"{message}." + (f" llama-server output: {detail}" if detail else "")

    async def _stop_server(self) -> None:
        process, self._process = self._process, None
        log, self._log = self._log, None
        self._client = None
        self._port = None

        async def release():
            try:
                if process is not None:
                    if process.returncode is None:
                        with suppress(ProcessLookupError):
                            process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            with suppress(ProcessLookupError):
                                process.kill()
                            await process.wait()
                    else:
                        await process.wait()
            finally:
                try:
                    if process is not None and process.returncode is None:
                        with suppress(ProcessLookupError):
                            process.kill()
                        await process.wait()
                finally:
                    if log is not None:
                        log.close()

        cleanup = asyncio.create_task(release())
        cancelled = False
        while True:
            try:
                await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError:
                cancelled = True
                if cleanup.done():
                    break
        if cancelled or cleanup.cancelled():
            raise asyncio.CancelledError

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_idle_timer()
            await self._stop_server()
