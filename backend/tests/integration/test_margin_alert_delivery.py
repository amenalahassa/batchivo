"""Where the margin-divergence alert actually goes (task T172).

FR-042 requires the operator be *alerted*, not merely able to ask. The sweep
used to report a divergence with ``logger.warning`` into a worker's log and
nothing else -- its own docstring recorded the destination as left open -- so an
operator who set ``margin_alert_threshold_pct`` on the pricing-policy screen
was never told when a line crossed it.

The specification left in-app versus email open, and it is both:

* in-app, through ``GET /reconciliation/margin-divergence``, which
  ``MarginDivergencePanel`` now reads;
* by email, through ``margin_alerts.deliver``, which this file covers.

``settled`` and ``reload_item`` come from ``tests/integration/conftest.py``, the
same fixtures ``test_margin_alert.py`` uses -- a second settled order would be
comparing against a different plan.
"""

import logging
from uuid import uuid4

import pytest

from tests.integration.conftest import reload_item
from tests.integration.test_margin_alert import (
    A_THRESHOLD_NOTHING_REACHES,
    A_THRESHOLD_THIS_SALE_PASSES,
    set_threshold,
)

from app.tasks import margin_alerts

#: The threshold helper and its two values are the ones `test_margin_alert.py`
#: already uses. Importing them rather than writing a second copy keeps both
#: files judging the same settled order against the same plan.
pytestmark = pytest.mark.asyncio


class _Recorder:
    """A configured mailer that records what it was asked to send."""

    is_configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str], str | None]] = []

    async def send_margin_divergence_alert(self, to_email, lines, *, since=None):
        self.sent.append((to_email, list(lines), since))
        return True


class TestTheAlertReachesSomebody:
    async def test_it_emails_the_tenants_owners_and_admins(
        self, db_session, test_tenant, test_user, settled, monkeypatch
    ) -> None:
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        recorder = _Recorder()
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: recorder)

        await margin_alerts.sweep_tenant(db_session, test_tenant)

        assert recorder.sent, "a divergence past the threshold must reach somebody"
        assert test_user.email in [address for address, _, _ in recorder.sent]

    async def test_the_email_names_the_lines_that_moved(
        self, db_session, test_tenant, test_user, settled, monkeypatch
    ) -> None:
        """US7 scenario 3: not that a product underperformed, but what moved.

        A shortfall whose cause is named is a decision the operator can make
        this afternoon; one that is not sends them through three screens to
        find out whether it was the fee schedule or the filament.
        """
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        recorder = _Recorder()
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: recorder)

        await margin_alerts.sweep_tenant(db_session, test_tenant)

        assert recorder.sent
        body = "\n".join(recorder.sent[0][1])
        assert "fees" in body, "the moved lines are the point of the alert"
        assert "threshold" in body, "the reader must know what it was measured against"

    async def test_it_sends_one_message_per_recipient_not_one_per_finding(
        self, db_session, test_tenant, test_user, settled, monkeypatch
    ) -> None:
        """An operator with three diverging products gets one email, not three."""
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        recorder = _Recorder()
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: recorder)

        found = await margin_alerts.sweep_tenant(db_session, test_tenant)

        addresses = [address for address, _, _ in recorder.sent]
        assert addresses, "the tenant's owner must have been emailed"
        assert len(addresses) == len(set(addresses)), "nobody is emailed twice"
        # Every finding travels in the one message.
        assert all(len(lines) == len(found) for _, lines, _ in recorder.sent)


class TestNothingIsSentWithoutCause:
    async def test_nothing_is_sent_when_nothing_diverged(
        self, db_session, test_tenant, test_user, settled, monkeypatch
    ) -> None:
        await set_threshold(db_session, test_tenant, A_THRESHOLD_NOTHING_REACHES)
        recorder = _Recorder()
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: recorder)

        await margin_alerts.sweep_tenant(db_session, test_tenant)

        assert recorder.sent == [], "an alert about nothing trains the operator to ignore alerts"

    async def test_an_unconfigured_mailer_is_not_an_error(
        self, db_session, test_tenant, settled, monkeypatch
    ) -> None:
        """The in-app list and the log are still destinations."""

        class Unconfigured:
            is_configured = False

            async def send_margin_divergence_alert(self, to_email, lines, *, since=None):
                raise AssertionError("must not try to send without configuration")

        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: Unconfigured())

        assert await margin_alerts.sweep_tenant(db_session, test_tenant)


class TestDeliveryFailureDoesNotLoseTheFinding:
    async def test_the_findings_are_still_logged_when_the_email_fails(
        self, db_session, test_tenant, settled, monkeypatch, caplog
    ) -> None:
        """A sweep whose delivery failed must leave a trace that it found something."""

        class Failing:
            is_configured = True

            async def send_margin_divergence_alert(self, to_email, lines, *, since=None):
                raise RuntimeError("the mail host is down")

        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: Failing())

        with caplog.at_level(logging.WARNING, logger="app.tasks.margin_alerts"):
            found = await margin_alerts.sweep_tenant(db_session, test_tenant)

        assert found, "a failed email must not swallow the finding"
        assert any("diverges" in record.getMessage() for record in caplog.records)


class TestWhoIsTold:
    async def test_recipients_are_the_roles_that_can_act(
        self, db_session, test_tenant, test_user
    ) -> None:
        """A margin is monetary policy, so a viewer is not told about it.

        A member who cannot change a price would be told about a problem they
        cannot fix, which is noise; a viewer is read-only by definition.
        """
        from app.models.user import User, UserRole, UserTenant

        viewer = User(
            id=uuid4(),
            email=f"viewer-{uuid4().hex[:8]}@example.com",
            full_name="A Viewer",
            is_active=True,
        )
        viewer.set_password("a-test-only-password")
        db_session.add(viewer)
        await db_session.flush()
        db_session.add(
            UserTenant(
                id=uuid4(),
                user_id=viewer.id,
                tenant_id=test_tenant.id,
                role=UserRole.VIEWER,
            )
        )
        await db_session.commit()

        addresses = await margin_alerts.recipients(db_session, test_tenant)

        assert test_user.email in addresses
        assert viewer.email not in addresses

    async def test_an_inactive_user_is_not_emailed(
        self, db_session, test_tenant, test_user
    ) -> None:
        from app.models.user import User, UserRole, UserTenant

        former = User(
            id=uuid4(),
            email=f"former-{uuid4().hex[:8]}@example.com",
            full_name="A Former Admin",
            is_active=False,
        )
        former.set_password("a-test-only-password")
        db_session.add(former)
        await db_session.flush()
        db_session.add(
            UserTenant(
                id=uuid4(),
                user_id=former.id,
                tenant_id=test_tenant.id,
                role=UserRole.ADMIN,
            )
        )
        await db_session.commit()

        addresses = await margin_alerts.recipients(db_session, test_tenant)

        assert former.email not in addresses

    async def test_a_tenant_with_nobody_to_tell_is_reported_not_crashed(
        self, db_session, test_tenant, settled, monkeypatch, caplog
    ) -> None:
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: _Recorder())
        monkeypatch.setattr(margin_alerts, "recipients", _no_recipients)

        with caplog.at_level(logging.WARNING, logger="app.tasks.margin_alerts"):
            assert await margin_alerts.sweep_tenant(db_session, test_tenant)

        assert any("no active owner or admin" in record.getMessage() for record in caplog.records)


async def _no_recipients(db, tenant):
    """A tenant whose owners have all been deactivated."""
    return []


class TestTheSweepStillWritesNothing:
    async def test_delivering_an_alert_moves_no_figure(
        self, db_session, test_tenant, settled, monkeypatch
    ) -> None:
        """FR-038: a divergence is an observation about history, not a correction.

        Telemetry proposes; it does not reprice. Adding a destination must not
        have added a write.
        """
        await set_threshold(db_session, test_tenant, A_THRESHOLD_THIS_SALE_PASSES)
        monkeypatch.setattr("app.services.email_service.get_email_service", lambda: _Recorder())

        before = (await reload_item(db_session, settled["order"])).make_cost_at_sale

        await margin_alerts.sweep_tenant(db_session, test_tenant)
        await db_session.commit()

        after = (await reload_item(db_session, settled["order"])).make_cost_at_sale
        assert after == before
