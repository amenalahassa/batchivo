"""The Celery application.

Celery was configured in ``app/config.py`` long before anything used it: a
broker URL, a result backend, and no task modules or worker anywhere. This is
the wiring, not a new technology choice (research.md D4).

**The broker URL matters in production.** The configured default is
``redis://localhost:6379/1``, which resolves to nothing inside a Kubernetes
pod. The worker manifest sets ``CELERY_BROKER_URL`` to the cluster Redis
service; without it the worker starts, connects to nothing and every scenario
sits queued -- which is why the dispatch path treats an unreachable broker as a
failed run with a reason rather than leaving a row to look like it is working
(FR-044b).
"""

import asyncio
import logging
import sys

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    # Tasks run their async work with `asyncio.run`, and psycopg's async mode
    # cannot use the Proactor loop Windows defaults to. Production runs on
    # Linux; this is what lets a worker run on a Windows development machine.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()

celery_app = Celery(
    "batchivo",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.scenario",
        "app.tasks.margin_alerts",
        # The observed-data loop (FR-042). These two were written, tested and
        # left off this list, so `variance_service.consider_outcomes` had no
        # reachable caller: no estimate was ever revised, no proposal ever
        # reached the review list, and no cost line ever acquired an observed
        # origin in a running system (task T148).
        "app.tasks.telemetry",
        "app.tasks.power",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A catalogue sweep is long and idempotent per run: the run row's terminal
    # state makes a retry a no-op, so late acknowledgement costs nothing and
    # buys back a job whose worker died mid-sweep.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # No result expiry games: the answer lives in `scenario_runs`, not in the
    # backend. The backend holds task plumbing, and losing it must not lose a
    # result an operator asked for (research.md D4).
    result_expires=3600,
    worker_max_tasks_per_child=100,
)

# The realised-margin sweep (FR-042). Daily, because that is the rhythm an
# operator reviews margins on -- hourly would turn an alert into noise, and
# weekly would let a fee-schedule change sit unnoticed for six days.
#
# It needs `celery beat` running, which the worker manifest starts alongside
# the worker. Without beat the task is still callable by hand and the console
# still reads the same findings from the endpoint, so a missing beat costs the
# notification, not the figure.
celery_app.conf.beat_schedule = {
    "margin-alerts-daily": {
        "task": "margin_alerts.sweep",
        # 06:00 UTC: after the night's prints have been recorded and before
        # the operator starts pricing anything.
        "schedule": crontab(hour="6", minute="0"),
    },
    # What the shop's own completed runs say about its estimates (FR-042a,
    # FR-042b). Daily and *before* the margin sweep, so the morning's
    # divergence report is read against estimates that already know what
    # yesterday's runs showed.
    #
    # It needs no printer to answer: it learns from a run's recorded duration
    # and purge columns, which is why this loop can close on the data the
    # operator already enters (task T148).
    "telemetry-learning-daily": {
        "task": "telemetry.learn",
        "schedule": crontab(hour="5", minute="0"),
    },
}

# `power.ingest` and `telemetry.ingest_run` are deliberately absent from the
# schedule. Both take their subject as an argument -- one printer's readings,
# one finished run -- and there is nothing to sweep: no store of plug readings
# exists, and the moment worth asking a printer what a job consumed is when the
# job ends, not on the hour. A schedule over an empty source would read in the
# log as a working integration and would not be one.


__all__ = ["celery_app"]
