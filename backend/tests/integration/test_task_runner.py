"""Back-to-back tasks in one worker process both reach the database.

Regression for `.specify/bugs/celery-task-loop-pool`: each task ran its work
with a bare `asyncio.run`, the module-level engine kept the connection the first
task opened, and the second task was handed it after its loop had closed --
`RuntimeError: Event loop is closed`, and a scenario run left `queued`.
"""

import asyncio

from sqlalchemy import text

from app.tasks import margin_alerts, scenario
from app.tasks.runner import run_in_task_loop


async def _select_one() -> int:
    from app.database import engine

    async with engine.connect() as connection:
        return (await connection.execute(text("SELECT 1"))).scalar_one()


def _two_tasks_in_a_row() -> list[int]:
    """What a single worker process does: one loop per task, one after the other."""
    return [run_in_task_loop(_select_one()), run_in_task_loop(_select_one())]


class TestTasksShareAProcessSafely:
    async def test_the_second_task_gets_a_connection_of_its_own_loop(self) -> None:
        # In a thread: the test itself runs inside an event loop, and each
        # task must create and close its own, as a worker does.
        assert await asyncio.to_thread(_two_tasks_in_a_row) == [1, 1]

    async def test_the_pool_is_left_empty_after_a_task(self) -> None:
        from app.database import engine

        await asyncio.to_thread(run_in_task_loop, _select_one())

        assert engine.pool.checkedin() == 0
        assert engine.pool.checkedout() == 0

    def test_the_pricing_tasks_run_through_the_runner(self) -> None:
        assert scenario.run_in_task_loop is run_in_task_loop
        assert margin_alerts.run_in_task_loop is run_in_task_loop
