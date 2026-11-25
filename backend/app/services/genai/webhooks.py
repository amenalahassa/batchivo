"""Provider webhook: verify the signature, then complete the job (research R8).

Replicate signs webhooks with the Standard Webhooks scheme: HMAC-SHA256 over
``"{webhook-id}.{webhook-timestamp}.{raw body}"`` with the base64-decoded part
of the ``whsec_…`` secret, sent as space-separated ``v1,<base64>`` entries in
``webhook-signature``. The tenant comes from the URL path; the session is
scoped to it before any query, and nothing is written unless the signature,
the timestamp and the prediction id all check out.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rls import set_rls_context
from app.models.generation_job import GenerationJob
from app.models.tenant import Tenant
from app.services.genai import credentials
from app.services.genai.base import ProviderError
from app.services.genai.errors import GenAIError, NotFound
from app.services.genai.replicate import parse_prediction

logger = logging.getLogger(__name__)

TOLERANCE_SECONDS = 300


class InvalidSignature(GenAIError):
    code = "invalid_signature"
    http_status = 401


def _secret_bytes(secret: str) -> bytes:
    raw = secret[len("whsec_") :] if secret.startswith("whsec_") else secret
    try:
        return base64.b64decode(raw)
    except (binascii.Error, ValueError) as exc:
        raise InvalidSignature("Unusable webhook secret") from exc


def sign(secret: str, webhook_id: str, timestamp: str, body: bytes) -> str:
    """The ``v1,<base64>`` signature of a body (used by tests and the e2e fake)."""
    content = f"{webhook_id}.{timestamp}.".encode() + body
    digest = hmac.new(_secret_bytes(secret), content, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify_webhook(
    secret: str, headers: Mapping[str, str], body: bytes, now: Optional[float] = None
) -> None:
    """Raise ``InvalidSignature`` unless the request was signed with ``secret`` recently."""
    lower = {k.lower(): v for k, v in headers.items()}
    webhook_id = lower.get("webhook-id")
    timestamp = lower.get("webhook-timestamp")
    signatures = lower.get("webhook-signature")
    if not webhook_id or not timestamp or not signatures:
        raise InvalidSignature("Missing webhook signature headers")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise InvalidSignature("Invalid webhook timestamp") from exc
    now = time.time() if now is None else now
    if abs(now - sent_at) > TOLERANCE_SECONDS:
        raise InvalidSignature("Webhook timestamp outside the tolerance")
    expected = sign(secret, webhook_id, timestamp, body).split(",", 1)[1]
    for candidate in signatures.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return
    raise InvalidSignature("Webhook signature does not match")


async def handle_replicate_webhook(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    headers: Mapping[str, str],
    body: bytes,
) -> GenerationJob:
    """Verify and apply one webhook call; idempotent for a job that already ended."""
    from app.services.genai import runner

    await set_rls_context(db, tenant_id=tenant_id)
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise NotFound("Unknown tenant")
    job = await db.scalar(
        select(GenerationJob).where(
            GenerationJob.id == job_id, GenerationJob.tenant_id == tenant_id
        )
    )
    if job is None or not job.external_id:
        raise NotFound("Unknown generation job")
    resolved = credentials.resolve(tenant)
    if not resolved.token:
        raise InvalidSignature("No token to verify this webhook with")
    provider = runner.make_provider(job.provider, resolved.token)
    try:
        secret = await credentials.webhook_secret(tenant, resolved, provider)
    except ProviderError as exc:
        raise InvalidSignature(f"Could not fetch the signing secret: {exc}") from exc
    finally:
        await provider.aclose()
    if secret is None:
        raise InvalidSignature("No signing secret")
    verify_webhook(secret, headers, body)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InvalidSignature("Webhook body is not JSON") from exc
    if not isinstance(payload, dict) or str(payload.get("id")) != job.external_id:
        raise NotFound("The webhook does not match this job")
    # Persist a newly fetched secret even when the job already ended.
    await db.commit()
    prediction = parse_prediction(payload)
    if job.status != "running" or not prediction.is_terminal:
        return job
    logger.info(f"Webhook completes generation job {job.id}")
    return await runner.complete_job(db, tenant, job.id, prediction) or job


__all__ = [
    "InvalidSignature",
    "TOLERANCE_SECONDS",
    "handle_replicate_webhook",
    "sign",
    "verify_webhook",
]
