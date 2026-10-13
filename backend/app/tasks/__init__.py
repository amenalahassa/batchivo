"""Background work: catalogue-wide scenarios, telemetry and power ingestion.

Nothing in this package is imported by the request path at module scope, and
nothing here is authoritative. A scenario writes no cost, price or provenance
figure (FR-044d); ingestion writes what a machine reported and routes every
estimate change through ``app.services.variance_service``, so a faulty sensor
raises a question instead of repricing a catalogue (FR-042b).

The Celery application lives in :mod:`app.tasks.celery_app`. Each task is a
thin wrapper around a service or an async ingestion function, so the work is
testable without a broker -- which is how the suite exercises it.
"""
