"""Shared background event loop.

ZYKO exposes both async and sync APIs. Instead of spawning a fresh event loop
per sync call (which breaks ``httpx`` client reuse and nested-loop rules),
every sync entrypoint funnels through one daemon thread that owns a single
``asyncio`` loop. This is what makes the same code run as a CLI one-liner, a
long-lived gateway, and inside GUI threads on Android without changes.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import threading
from typing import AsyncIterator, Awaitable, Iterator, TypeVar

T = TypeVar("T")


class SharedLoop:
    """A lazily-started, process-wide background event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._thread is None or not self._thread.is_alive():
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._run, name="zyko-io", daemon=True)
                self._thread.start()
            return self._loop

    def _run(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def submit(self, coro: Awaitable[T]) -> "concurrent.futures.Future[T]":
        """Schedule *coro* on the shared loop; returns a ``Future``."""
        return asyncio.run_coroutine_threadsafe(coro, self._ensure())

    def run(self, coro: Awaitable[T], timeout: float | None = None) -> T:
        """Run *coro* on the shared loop and block until it finishes."""
        return self.submit(coro).result(timeout)

    def iterate(self, agen: AsyncIterator[T], *, cancel_on_close: bool = True) -> Iterator[T]:
        """Bridge an async iterator into a sync iterator via a queue."""
        q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        task_holder: dict[str, object] = {}

        async def _pump() -> None:
            try:
                async for item in agen:
                    q.put(("item", item))
            except BaseException as exc:  # noqa: BLE001 - propagated to consumer
                q.put(("error", exc))
            finally:
                q.put(("done", None))

        try:
            task_holder["task"] = self.submit(_pump())
            while True:
                kind, value = q.get()
                if kind == "item":
                    yield value  # type: ignore[misc]
                elif kind == "error":
                    raise value  # type: ignore[misc]
                else:
                    break
        except GeneratorExit:
            if cancel_on_close and "task" in task_holder:
                task_holder["task"].cancel()  # type: ignore[union-attr]
            raise


SHARED_LOOP = SharedLoop()


def run_sync(coro: Awaitable[T], timeout: float | None = None) -> T:
    """Run *coro* to completion from synchronous code, anywhere.

    - No running loop  → execute on the shared loop (reuses connections).
    - Running loop     → delegate to the shared loop from a helper thread so we
      never block or dead-lock the caller's loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return SHARED_LOOP.run(coro, timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: SHARED_LOOP.run(coro, timeout)).result()
