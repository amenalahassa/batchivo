"""Run a task's async work in its own event loop, and leave no connection behind.

A Celery task runs its coroutine with `asyncio.run`, which creates a loop and
closes it when the coroutine returns. The database engine in `app.database` is
module-level, so its pool outlives that loop: the next task in the same worker
process is handed a pooled connection whose transport belongs to the closed
loop, and fails with `RuntimeError: Event loop is closed` before it does any
work. With one worker process that is every other task, and a scenario run left
`queued` for ever is exactly the hanging job FR-044b forbids.

:func:`run_in_task_loop` disposes of the pool inside the task's own loop, while
that loop can still close the connections, so every task starts from an empty
pool.
"""

import asyncio
from typing import Awaitable, TypeVar

T = TypeVar("T")


def run_in_task_loop(work: Awaitable[T]) -> T:
    """`asyncio.run(work)`, then return the engine's connections to nobody."""

    async def _run() -> T:
        from app.database import engine

        try:
            return await work
        finally:
            await engine.dispose()

    return asyncio.run(_run())


__all__ = ["run_in_task_loop"]
