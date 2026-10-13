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

import logging

from celery import Celery

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "batchivo",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.scenario"],
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


__all__ = ["celery_app"]
