"""The worker wrappers of generation jobs (spec 008, research R6, finding F6).

``app.tasks.genai`` is thin: each wrapper opens a tenant-scoped session, runs one
runner step and chains the next one. These tests run the wrappers with the test
session standing in for ``async_session_maker`` and record what they dispatch;
no broker is reached and Replicate is mocked.
"""

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest

import app.tasks.genai as tasks
from app.models.generation_job import GenerationJob
from app.services.genai.service import GenAIService, JobRequest
from tests.utils.genai import prediction, provider_url

# The real dispatchers, captured before the autouse ``dispatched`` fixture replaces them.
REAL_DISPATCH_SUBMIT = tasks.dispatch_submit
REAL_DISPATCH_POLL = tasks.dispatch_poll


class _SessionContext:
    """``async with async_session_maker() as db`` yielding the test session, left open."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def worker_session(monkeypatch, db_session):
    """Run the wrappers on the test session; record the RLS scope they set."""
    import app.core.rls as rls
    import app.database as database

    scoped: list = []

    async def fake_rls(db, *, tenant_id=None, user_id=None):
        scoped.append(tenant_id)

    monkeypatch.setattr(database, "async_session_maker", lambda: _SessionContext(db_session))
    monkeypatch.setattr(rls, "set_rls_context", fake_rls)
    return scoped


@pytest.fixture
def chained(monkeypatch):
    """Record the next steps a wrapper schedules, with their arguments."""
    calls: dict[str, list] = {"submit": [], "poll": []}
    monkeypatch.setattr(
        tasks,
        "dispatch_submit",
        lambda job_id, tenant_id, **kw: calls["submit"].append((job_id, tenant_id, kw)),
    )
    monkeypatch.setattr(
        tasks,
        "dispatch_poll",
        lambda job_id, tenant_id, delay: calls["poll"].append((job_id, tenant_id, delay)),
    )
    return calls


def _step(monkeypatch, name: str, result):
    """Replace one runner step by a recorder returning ``result``."""
    from app.services.genai import runner

    seen: list = []

    async def step(db, tenant, *args):
        seen.append((tenant.id, args))
        return result

    monkeypatch.setattr(runner, name, step)
    return seen


# ============================================
# Tenant scope
# ============================================


async def test_with_tenant_scopes_the_session(worker_session, test_tenant):
    async def work(db, tenant):
        return tenant.id

    assert await tasks._with_tenant(test_tenant.id, work) == test_tenant.id
    assert worker_session == [test_tenant.id]


async def test_with_tenant_of_a_gone_tenant_does_nothing(worker_session):
    called = []

    async def work(db, tenant):
        called.append(tenant)

    assert await tasks._with_tenant(uuid.uuid4(), work) is None
    assert called == []


# ============================================
# run_submit / run_poll chaining
# ============================================


async def test_run_submit_chains_the_first_poll(monkeypatch, worker_session, chained, test_tenant):
    job_id = uuid.uuid4()
    seen = _step(monkeypatch, "submit_job", 2.0)
    assert await tasks.run_submit(job_id, test_tenant.id) == 2.0
    assert seen == [(test_tenant.id, (job_id, 1))]
    assert chained["poll"] == [(job_id, test_tenant.id, 2.0)]
    assert chained["submit"] == []


async def test_run_submit_retries_with_a_growing_delay(
    monkeypatch, worker_session, chained, test_tenant
):
    job_id = uuid.uuid4()
    _step(monkeypatch, "submit_job", -1.0)
    await tasks.run_submit(job_id, test_tenant.id, attempt=2)
    assert chained["submit"] == [(job_id, test_tenant.id, {"attempt": 3, "delay": 10.0})]
    assert chained["poll"] == []


async def test_run_submit_stops_when_nothing_is_left(
    monkeypatch, worker_session, chained, test_tenant
):
    _step(monkeypatch, "submit_job", None)
    assert await tasks.run_submit(uuid.uuid4(), test_tenant.id) is None
    assert chained == {"submit": [], "poll": []}


async def test_run_poll_chains_until_the_job_ends(
    monkeypatch, worker_session, chained, test_tenant
):
    job_id = uuid.uuid4()
    _step(monkeypatch, "poll_job", 4.5)
    assert await tasks.run_poll(job_id, test_tenant.id) == 4.5
    assert chained["poll"] == [(job_id, test_tenant.id, 4.5)]
    _step(monkeypatch, "poll_job", None)
    assert await tasks.run_poll(job_id, test_tenant.id) is None
    assert len(chained["poll"]) == 1


async def test_run_submit_end_to_end(
    db_session, connected_tenant, replicate_mock, worker_session, chained
):
    """The real runner step behind the wrapper: queued → running, first poll chained."""
    job = await GenAIService(db_session, connected_tenant).create_job(
        JobRequest("concept_image", {"prompt": "a hook"})
    )
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(201, json=prediction(status="starting"))
    )
    assert await tasks.run_submit(job.id, connected_tenant.id) == 2.0
    job = await db_session.get(GenerationJob, job.id, populate_existing=True)
    assert job.status == "running"
    assert chained["poll"] == [(job.id, connected_tenant.id, 2.0)]


# ============================================
# run_sweep
# ============================================


async def test_run_sweep_polls_what_the_sweep_found(
    monkeypatch, worker_session, chained, test_tenant
):
    from app.services.genai import runner

    stale = uuid.uuid4()

    async def sweep(db, tenant, now=None):
        if tenant.id == test_tenant.id:
            return {"failed_queued": 1, "timed_out": 2, "to_poll": [stale]}
        return {"failed_queued": 0, "timed_out": 0, "to_poll": []}

    monkeypatch.setattr(runner, "sweep_tenant", sweep)
    assert await tasks.run_sweep() == 4
    assert chained["poll"] == [(stale, test_tenant.id, 0)]


async def test_run_sweep_skips_inactive_tenants(
    monkeypatch, db_session, worker_session, chained, test_tenant
):
    from app.services.genai import runner

    swept: list = []

    async def sweep(db, tenant, now=None):
        swept.append(tenant.id)
        return {"failed_queued": 0, "timed_out": 0, "to_poll": []}

    monkeypatch.setattr(runner, "sweep_tenant", sweep)
    test_tenant.is_active = False
    await db_session.commit()
    assert await tasks.run_sweep() == 0
    assert test_tenant.id not in swept


# ============================================
# Dispatch: inline (dev/e2e) and broker
# ============================================


@pytest.fixture
def inline(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "genai_run_inline", True)
    assert get_settings().genai_inline


async def _drain():
    for _ in range(5):
        pending = list(tasks._inline_tasks)
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def test_inline_dispatch_runs_the_steps_in_process(monkeypatch, inline):
    ran: list = []

    async def fake_submit(job_id, tenant_id, attempt=1):
        ran.append(("submit", job_id, attempt))

    async def fake_poll(job_id, tenant_id):
        ran.append(("poll", job_id))

    monkeypatch.setattr(tasks, "run_submit", fake_submit)
    monkeypatch.setattr(tasks, "run_poll", fake_poll)
    job_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    assert REAL_DISPATCH_SUBMIT(job_id, tenant_id, attempt=2) is None
    assert REAL_DISPATCH_POLL(job_id, tenant_id, 0.01) is None
    await _drain()
    assert sorted(ran, key=str) == sorted([("submit", job_id, 2), ("poll", job_id)], key=str)
    assert not tasks._inline_tasks


async def test_inline_step_failure_is_logged_not_raised(monkeypatch, inline, caplog):
    async def broken(job_id, tenant_id, attempt=1):
        raise RuntimeError("worker blew up")

    monkeypatch.setattr(tasks, "run_submit", broken)
    REAL_DISPATCH_SUBMIT(uuid.uuid4(), uuid.uuid4())
    with caplog.at_level("ERROR", logger="app.tasks.genai"):
        await _drain()
    assert "Inline generation step failed: RuntimeError" in caplog.text


def test_broker_dispatch_uses_countdown(monkeypatch):
    sent: list = []

    def apply_async(args, countdown=None):
        sent.append((args, countdown))
        return SimpleNamespace(id="celery-1")

    monkeypatch.setattr(tasks.submit_task, "apply_async", apply_async)
    monkeypatch.setattr(tasks.poll_task, "apply_async", apply_async)
    job_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    assert REAL_DISPATCH_SUBMIT(job_id, tenant_id, attempt=2, delay=5.0) == "celery-1"
    assert REAL_DISPATCH_POLL(job_id, tenant_id, 0) == "celery-1"
    assert sent == [
        ([str(job_id), str(tenant_id), 2], 5.0),
        ([str(job_id), str(tenant_id)], None),
    ]


def test_broker_down_submit_raises_poll_does_not(monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks.submit_task, "apply_async", down)
    monkeypatch.setattr(tasks.poll_task, "apply_async", down)
    with pytest.raises(ConnectionError):
        REAL_DISPATCH_SUBMIT(uuid.uuid4(), uuid.uuid4())
    # the sweep re-polls a job whose chain broke
    assert REAL_DISPATCH_POLL(uuid.uuid4(), uuid.uuid4(), 3.0) is None


def test_celery_tasks_run_the_wrappers(monkeypatch):
    ran: list = []

    def fake_loop(work):
        ran.append(work.__qualname__)
        work.close()
        return "done"

    monkeypatch.setattr(tasks, "run_in_task_loop", fake_loop)
    job_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    assert tasks.submit_task(job_id, tenant_id, 2) == "done"
    assert tasks.poll_task(job_id, tenant_id) == "done"
    assert tasks.sweep_task() == "done"
    assert ran == ["run_submit", "run_poll", "run_sweep"]
