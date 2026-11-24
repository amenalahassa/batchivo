# Bug Assessment: Every other Celery task in a worker process fails with "Event loop is closed"

- **Slug**: celery-task-loop-pool
- **Created**: 2026-11-24
- **Source**: pasted text (found while fixing `scenario.spec.ts`, after `cost-load-options-depth-slow`)
- **Verdict**: valid (app defect)
- **Severity**: high (scenario runs stay `queued` for ever, which FR-044b forbids; the same pattern sits in every task module)

## Report (verbatim or summarized)

Worker log, one `--pool=solo` worker, consecutive scenario runs:

```
Task scenario.run[c0166bf1-...] succeeded in 2.69s: 'succeeded'
Task scenario.run[9e3e83ab-...] received
ERROR Exception terminating connection <AdaptedConnection <asyncpg.connection.Connection ...>>
Task scenario.run[9e3e83ab-...] raised unexpected: RuntimeError("... attached to a different loop")
Task scenario.run[2afe3f6a-...] succeeded in 0.42s: 'succeeded'
Task scenario.run[86821bdc-...] raised unexpected: RuntimeError('Event loop is closed')
```

The scenario journey then waits for a terminal state that never comes (test timeout).

## Symptom

In one worker process, task N runs, task N+1 fails before doing any work, task N+2 runs,
and so on. The failed scenario run stays `queued` and the screen waits on it for ever.
Expected: every task runs.

## Reproduction

1. Start one Celery worker (`--pool=solo`, or any prefork child: `worker_max_tasks_per_child=100`).
2. Request two scenarios in a row.
3. The second task fails with `Event loop is closed` / `attached to a different loop`.

## Suspected Code Paths

- `backend/app/tasks/scenario.py:run_scenario_task`: `asyncio.run(_run(...))`.
- `backend/app/database.py`: `engine` is module-level, `pool_size=10`, `pool_pre_ping=True`.
  The pool keeps the connection opened in the first task's loop. Pre-ping on the next
  checkout runs in a new loop against a transport owned by the closed one.
- Same `asyncio.run` pattern: `margin_alerts.py`, `telemetry.py` (x2), `power.py`, `mesh_measure.py`.

## Root Cause Hypothesis

`asyncio.run` closes its loop when the task returns, and the module-level pool outlives
it. The next task gets a pooled asyncpg/psycopg connection bound to a dead loop. The failure
invalidates the pool, so the task after it works again. Confidence: high (log above; the
regression test fails without the fix, see fix.md).

## Proposed Remediation

**Preferred**: one helper, `app/tasks/runner.py:run_in_task_loop(work)`. It runs the coroutine
in a fresh loop and calls `await engine.dispose()` in a `finally` inside that loop, so each task
starts from an empty pool. Use it in the pricing tasks (`scenario`, `margin_alerts`).

**Alternatives**:
- `NullPool` for workers: needs a worker-specific engine, which is a larger change in `database.py`.
- A persistent loop per worker process: more machinery for the same result.

**Files likely to change**:
- `backend/app/tasks/runner.py` (new), `backend/app/tasks/scenario.py`, `backend/app/tasks/margin_alerts.py`
- `backend/tests/integration/test_task_runner.py` (new)

**Tests to add or update**:
- Two tasks in a row in one thread (each with its own loop) both reach the database.
- The pool is empty after a task.

## Risks & Considerations

- Each task opens a fresh connection: negligible next to a catalogue sweep.
- `telemetry.py`, `power.py` and `mesh_measure.py` (printers/model files, the 011 zone) keep
  the bare `asyncio.run` and the same defect: a follow-up for their owner.

## Open Questions

- None for the pricing tasks.
