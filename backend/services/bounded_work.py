"""Bounded producer/consumer execution for connector sync work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

InputT = TypeVar("InputT")
ResultT = TypeVar("ResultT")


async def map_bounded(
    items: Iterable[InputT],
    handler: Callable[[InputT], Awaitable[ResultT]],
    *,
    concurrency: int,
    queue_capacity: int | None = None,
) -> list[ResultT]:
    """Process items with a fixed task count and backpressured input queue."""
    worker_count = max(1, concurrency)
    capacity = max(worker_count, queue_capacity or worker_count * 2)
    queue: asyncio.Queue[InputT | None] = asyncio.Queue(maxsize=capacity)
    results: list[ResultT] = []
    result_lock = asyncio.Lock()

    async def produce() -> None:
        for item in items:
            await queue.put(item)
        for _ in range(worker_count):
            await queue.put(None)

    async def consume() -> None:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                result = await handler(item)
                async with result_lock:
                    results.append(result)
            finally:
                queue.task_done()

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(produce())
        for _ in range(worker_count):
            tasks.create_task(consume())
    return results
