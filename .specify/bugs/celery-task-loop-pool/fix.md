# Bug Fix: Every other Celery task in a worker process fails with "Event loop is closed"

- **Slug**: celery-task-loop-pool
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`run_in_task_loop(work)` runs a task's coroutine in its own loop and disposes of the engine's
pool inside that loop, so the next task never inherits a connection bound to a closed loop.
Used by the pricing tasks.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/tasks/runner.py` | added | `run_in_task_loop` |
| `backend/app/tasks/scenario.py` | modified | uses it instead of `asyncio.run` |
| `backend/app/tasks/margin_alerts.py` | modified | same |
| `backend/tests/integration/test_task_runner.py` | added test | |

## Tests Added or Updated

- `test_task_runner.py::test_the_second_task_gets_a_connection_of_its_own_loop`: two tasks in a
  row in one thread both reach the database.
- `...::test_the_pool_is_left_empty_after_a_task`.
- `...::test_the_pricing_tasks_run_through_the_runner`.

## Local Verification

- With the `dispose` removed: 2 of 3 fail (pool not empty, `attached to a different loop`).
  With it: 3 passed.
- Scenario journey green in runs 9 and 10.

## Deviations from Assessment

None.

## Follow-ups

- `app/tasks/telemetry.py` (x2), `power.py` and `mesh_measure.py` keep a bare `asyncio.run`
  and the same defect. They are in the 011 zone (printers, model files) and were left alone;
  they should switch to `run_in_task_loop`.
