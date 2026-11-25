"""Every pod that touches the broker has its address (task T149).

`backend/app/config.py` defaults `celery_broker_url` to
`redis://localhost:6379/1`. Inside a Kubernetes pod that resolves to the pod
itself, where nothing is listening. The worker manifest set its own copy and
named the trap in its header; the *API* — which is what publishes, through
`apply_async` in `app/tasks/scenario.py` — was left on the default. So
`POST /scenarios` returned its 202 (FR-044a) and the run sat queued for ever,
which is the one failure FR-044b rules out: a job must surface a partial or
failed outcome rather than appear to hang.

## Why this is a test and not a deployment note

research.md D4 *was* a deployment note, and the note was half-applied for two
phases. A note cannot fail. This reads the manifests, so adding a third pod
that imports `celery_app` without the address fails here rather than in a
scenario an operator waits all afternoon for.

It is a text-level read on purpose: PyYAML is not a backend dependency, and
pulling one in to assert two strings would be a worse trade than the slightly
blunter check.
"""

import re
from pathlib import Path

import pytest

K8S = Path(__file__).resolve().parents[3] / "infrastructure" / "k8s" / "backend"

#: Manifests for pods that run this application's code.
POD_MANIFESTS = ("deployment.yaml", "celery-worker.yaml")

CONFIGMAP = K8S / "deployment.yaml"


def _text(name: str) -> str:
    path = K8S / name
    assert path.exists(), f"{path} is gone; this check moved with it or stopped running"
    return path.read_text(encoding="utf-8")


class TestTheBrokerAddressReachesEveryPod:
    def test_the_shared_configmap_carries_both_urls(self) -> None:
        """One copy, read by both pods. Two copies of one address drift."""
        text = _text("deployment.yaml")

        assert "CELERY_BROKER_URL:" in text, (
            "the API publishes to the broker; without this it publishes to "
            "its own pod and the run never arrives"
        )
        assert "CELERY_RESULT_BACKEND:" in text

    def test_both_point_at_the_cluster_redis_service(self) -> None:
        text = _text("deployment.yaml")

        assert 'CELERY_BROKER_URL: "redis://redis:6379/1"' in text
        assert 'CELERY_RESULT_BACKEND: "redis://redis:6379/2"' in text

    def test_they_are_clear_of_the_application_cache(self) -> None:
        """Database 0 is the application cache. A flush of one must not take
        the broker or the results with it."""
        text = _text("deployment.yaml")

        assert 'REDIS_URL: "redis://redis:6379/0"' in text
        assert "6379/0" not in text.split("CELERY_BROKER_URL:")[1].split("\n")[0]

    @pytest.mark.parametrize("manifest", POD_MANIFESTS)
    def test_no_pod_is_left_on_the_localhost_default(self, manifest: str) -> None:
        """The default resolves to the pod itself, where nothing listens."""
        text = _text(manifest)

        offenders = [
            line.strip()
            for line in text.splitlines()
            if "localhost:6379" in line and not line.strip().startswith("#")
        ]
        assert offenders == [], (
            f"{manifest} points a broker or result backend at localhost: {offenders}"
        )

    @pytest.mark.parametrize("manifest", POD_MANIFESTS)
    def test_every_pod_reads_the_shared_configmap(self, manifest: str) -> None:
        """Which is how it gets the address without carrying its own copy."""
        text = _text(manifest)

        assert re.search(r"configMapRef:\s*\n\s*name:\s*backend-config", text), (
            f"{manifest} does not read backend-config, so it has no broker "
            f"address unless it sets its own"
        )

    def test_the_worker_no_longer_keeps_a_second_copy(self) -> None:
        """It kept one while the publisher had none, which is how the two could
        disagree about where the queue is."""
        text = _text("celery-worker.yaml")

        settings = [
            line.strip() for line in text.splitlines() if line.strip().startswith("- name: CELERY_")
        ]
        assert settings == [], f"the worker sets its own broker env again: {settings}"


class TestTheDefaultItselfIsStillTheRiskThisGuardsAgainst:
    def test_the_configured_default_is_localhost(self) -> None:
        """If this ever stops being true the guard above is cargo. It is a
        reasonable default for a developer's machine and a trap in a cluster,
        which is exactly why the manifests must override it."""
        from app.config import Settings

        assert Settings.model_fields["celery_broker_url"].default.startswith("redis://localhost")

    def test_the_api_really_does_publish(self) -> None:
        """If the API stopped enqueueing, none of this would matter — and the
        reason it matters is a line of code, not a guess."""
        source = (Path(__file__).resolve().parents[2] / "app" / "tasks" / "scenario.py").read_text(
            encoding="utf-8"
        )

        assert "apply_async" in source
