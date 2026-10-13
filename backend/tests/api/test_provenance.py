"""Reading and writing where a figure came from, over HTTP (task T102).

Three things these endpoints must get right, and each has a wrong answer that
would seem defensible:

1. **Reading is open to every role, a viewer included** (FR-007c). This reads
   as a privilege and is not one: a viewer cannot judge a margin without seeing
   which figures behind it are measured and which are guesses. Hiding it leaves
   them trusting a number whose basis they cannot check.

2. **A write to an observed figure is refused** (FR-004). An observed figure is
   read-only and refreshed only from its source. Letting an operator overwrite
   the label by hand would make "observed" mean "somebody typed this", which is
   the one thing it must not mean. Refused with a 409 rather than a 403,
   because the operator has the role and the figure is the obstacle.

3. **A stale measurement is flagged while still showing its last value**
   (FR-005). Hiding a stale figure would leave the cost unexplained; showing it
   without the flag would leave a three-year-old measurement looking current.
   Both are worse than showing it and saying so.

The proposal endpoints are here too: listing is a read like the rest, and
accept and reject take a proposal whole (FR-042c).
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import clock
from app.models.model import Model
from app.models.user import UserRole
from app.services.provenance import record_origin
from app.services.variance_service import Outcome, consider_outcomes

FIELD = "print_time_minutes"
ENTITY_TYPE = "model"
TODAY = clock.today()


def _url(entity_type: str, entity_id) -> str:
    return f"/api/v1/provenance?entity_type={entity_type}&entity_id={entity_id}"


def _write_url(entity_type: str, entity_id, field_name: str) -> str:
    return f"/api/v1/provenance/{entity_type}/{entity_id}/{field_name}"


@pytest_asyncio.fixture
async def subject(db_session, test_tenant) -> Model:
    """A model with a figure worth asking about."""
    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"PROV-{uuid4().hex[:6]}",
        name="Provenance subject",
        print_time_minutes=100,
        prints_per_plate=1,
        waste_grams=Decimal("3"),
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    return model


# ---------------------------------------------------------------------------
# FR-007c: every role may read
# ---------------------------------------------------------------------------


class TestReadingIsOpenToEveryRole:
    async def test_a_viewer_can_read_provenance(self, as_role, subject) -> None:
        """The clause that reads as a privilege and is not one.

        A viewer who can see a margin but not what it rests on is a viewer who
        has to trust it.
        """
        async with as_role(UserRole.VIEWER) as client:
            response = await client.get(_url(ENTITY_TYPE, subject.id))

        assert response.status_code == 200, response.text
        assert response.json()["entity_id"] == str(subject.id)

    @pytest.mark.parametrize(
        "role", [UserRole.VIEWER, UserRole.MEMBER, UserRole.ADMIN, UserRole.OWNER]
    )
    async def test_every_role_reads_the_same_thing(self, as_role, subject, role) -> None:
        async with as_role(role) as client:
            response = await client.get(_url(ENTITY_TYPE, subject.id))

        assert response.status_code == 200, response.text
        assert response.json()["total_count"] > 0

    async def test_a_viewer_can_read_the_proposal_list(self, as_role) -> None:
        async with as_role(UserRole.VIEWER) as client:
            response = await client.get("/api/v1/estimate-revisions")

        assert response.status_code == 200, response.text


class TestWhatTheReadReports:
    async def test_a_field_with_no_recorded_origin_is_still_reported(
        self, client, subject
    ) -> None:
        """"Nobody has said" is the answer FR-001 wants shown.

        Omitting the field would make an unrecorded figure indistinguishable
        from one that does not exist.
        """
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["source"] == "assumed"
        assert entry["is_default"] is True
        assert entry["as_of"] is None, "nothing recorded is not the same as today"

    async def test_every_field_carries_a_description(self, client, subject) -> None:
        """A field name is not self-explanatory to the person pricing with it."""
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        assert all(field["description"] for field in body["fields"])

    async def test_a_recorded_origin_is_reported_with_its_date(
        self, client, db_session, test_tenant, subject
    ) -> None:
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="measured",
            as_of=TODAY - timedelta(days=3),
        )
        await db_session.commit()

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)

        assert entry["source"] == "measured"
        assert entry["as_of"] == str(TODAY - timedelta(days=3))
        assert entry["is_default"] is False

    async def test_the_observed_count_is_reported_against_the_total(
        self, client, db_session, test_tenant, subject
    ) -> None:
        """SC-010 measures this share, so it is served rather than recomputed."""
        before = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="measured",
        )
        await db_session.commit()

        after = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        assert after["observed_count"] == before["observed_count"] + 1
        assert after["total_count"] == before["total_count"]

    async def test_an_unknown_entity_type_is_refused_rather_than_empty(
        self, client, subject
    ) -> None:
        """An empty answer would read as "this record has no inputs"."""
        response = await client.get(_url("modle", subject.id))

        assert response.status_code == 422
        assert "modle" in response.text

    async def test_an_entity_that_does_not_exist_reports_defaults(
        self, client
    ) -> None:
        """Provenance is about field names, not about the record.

        A 404 would need a lookup per entity type for no gain; what comes back
        is the registry's view, every field defaulted, which is the truth.
        """
        response = await client.get(_url(ENTITY_TYPE, uuid4()))

        assert response.status_code == 200
        assert all(field["is_default"] for field in response.json()["fields"])


# ---------------------------------------------------------------------------
# FR-005: stale, and still showing its value
# ---------------------------------------------------------------------------


class TestStalenessIsFlaggedNotHidden:
    async def test_an_old_measurement_is_flagged(
        self, client, db_session, test_tenant, subject
    ) -> None:
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        threshold = body["staleness_threshold_days"]

        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="measured",
            as_of=TODAY - timedelta(days=threshold + 1),
        )
        await db_session.commit()

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)

        assert entry["is_stale"] is True
        assert body["stale_count"] >= 1

    async def test_a_stale_figure_still_shows_its_last_value_and_date(
        self, client, db_session, test_tenant, subject
    ) -> None:
        """The whole of FR-005. Hiding it would leave the cost unexplained."""
        measured_on = TODAY - timedelta(days=400)
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="measured",
            as_of=measured_on,
        )
        await db_session.commit()

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)

        assert entry["is_stale"] is True
        assert entry["source"] == "measured"
        assert entry["as_of"] == str(measured_on)
        assert subject.print_time_minutes == 100, "the figure itself is untouched"

    async def test_a_fresh_measurement_is_not_flagged(
        self, client, db_session, test_tenant, subject
    ) -> None:
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="measured",
            as_of=TODAY,
        )
        await db_session.commit()

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)

        assert entry["is_stale"] is False

    async def test_the_threshold_reported_is_the_tenants_own(
        self, client, subject
    ) -> None:
        """A count of stale figures cannot be judged without the threshold."""
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        assert body["staleness_threshold_days"] > 0

    async def test_a_policy_decision_does_not_go_stale(
        self, client, db_session, test_tenant, subject
    ) -> None:
        """A decision does not expire; only a measurement does (FR-005)."""
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="policy",
            as_of=TODAY - timedelta(days=4000),
        )
        await db_session.commit()

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)

        assert entry["is_stale"] is False


# ---------------------------------------------------------------------------
# FR-004: an observed figure is read-only
# ---------------------------------------------------------------------------


class TestAnObservedFigureIsNotEditable:
    @pytest_asyncio.fixture
    async def observed(self, db_session, test_tenant, subject):
        await record_origin(
            db_session,
            test_tenant,
            entity_type=ENTITY_TYPE,
            entity_id=subject.id,
            field_name=FIELD,
            source="observed",
            automated=True,
        )
        await db_session.commit()
        return subject

    async def test_a_write_is_refused(self, client, observed) -> None:
        response = await client.put(
            _write_url(ENTITY_TYPE, observed.id, FIELD),
            json={"source": "measured"},
        )

        assert response.status_code == 409, response.text
        assert "read-only" in response.text or "refreshed" in response.text

    async def test_the_refusal_is_a_conflict_not_a_forbidden(
        self, client, observed
    ) -> None:
        """403 would read as "ask an admin", which would not help.

        The operator has the role. The figure is the obstacle.
        """
        response = await client.put(
            _write_url(ENTITY_TYPE, observed.id, FIELD),
            json={"source": "measured"},
        )

        assert response.status_code != 403
        assert response.status_code == 409

    async def test_the_stored_origin_is_unchanged_after_the_refusal(
        self, client, observed
    ) -> None:
        await client.put(
            _write_url(ENTITY_TYPE, observed.id, FIELD), json={"source": "measured"}
        )

        body = (await client.get(_url(ENTITY_TYPE, observed.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["source"] == "observed"

    async def test_the_read_reports_it_as_not_editable(
        self, client, observed
    ) -> None:
        """So the screen can omit the edit rather than offer one that fails."""
        body = (await client.get(_url(ENTITY_TYPE, observed.id))).json()

        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["editable"] is False

    async def test_an_unrecorded_field_is_editable(self, client, subject) -> None:
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["editable"] is True

    async def test_observed_cannot_be_claimed_by_hand(self, client, subject) -> None:
        """The label belongs to the process that observed the figure.

        Without this, an operator could type "observed" and the share SC-010
        measures would stop meaning anything.
        """
        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, FIELD), json={"source": "observed"}
        )

        assert response.status_code == 422, response.text
        assert "observed" in response.text


# ---------------------------------------------------------------------------
# FR-007a: who may write what
# ---------------------------------------------------------------------------


class TestWhoMayWrite:
    async def test_a_member_may_record_a_measurement(self, as_role, subject) -> None:
        """Taking a measurement is a member's job."""
        async with as_role(UserRole.MEMBER) as client:
            response = await client.put(
                _write_url(ENTITY_TYPE, subject.id, FIELD),
                json={"source": "measured"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["source"] == "measured"

    async def test_a_viewer_may_not_write_at_all(self, as_role, subject) -> None:
        async with as_role(UserRole.VIEWER) as client:
            response = await client.put(
                _write_url(ENTITY_TYPE, subject.id, FIELD),
                json={"source": "measured"},
            )

        assert response.status_code == 403, response.text

    async def test_a_member_may_not_declare_a_policy_figure(
        self, as_role, subject
    ) -> None:
        """A policy figure is a monetary decision, so admin or owner (FR-007a).

        Claiming ``policy`` makes the write a decision whatever the field is,
        which is why the request's own source is read as well as the registry's
        classification -- otherwise a member could declare a policy on any
        measurable field and take it out of the automatic mechanism's reach.
        """
        async with as_role(UserRole.MEMBER) as client:
            response = await client.put(
                _write_url(ENTITY_TYPE, subject.id, FIELD),
                json={"source": "policy"},
            )

        assert response.status_code == 403, response.text

    async def test_an_admin_may_declare_a_policy_figure(
        self, as_role, subject
    ) -> None:
        async with as_role(UserRole.ADMIN) as client:
            response = await client.put(
                _write_url(ENTITY_TYPE, subject.id, FIELD),
                json={"source": "policy"},
            )

        assert response.status_code == 200, response.text

    async def test_a_member_may_not_write_an_unlearnable_policy_lever(
        self, as_role, test_tenant
    ) -> None:
        """A policy lever is a decision by construction, however it is labelled."""
        async with as_role(UserRole.MEMBER) as client:
            response = await client.put(
                _write_url("tenant_pricing_policy", test_tenant.id, "print_labor_rate"),
                json={"source": "measured"},
            )

        assert response.status_code == 403, response.text

    async def test_a_refused_write_leaves_the_figure_and_its_origin_untouched(
        self, as_role, client, subject
    ) -> None:
        """FR-007d, stated as the thing a reader would check afterwards."""
        async with as_role(UserRole.VIEWER) as viewer:
            await viewer.put(
                _write_url(ENTITY_TYPE, subject.id, FIELD),
                json={"source": "measured"},
            )

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["is_default"] is True
        assert subject.print_time_minutes == 100


class TestWritingTheOrigin:
    async def test_a_write_records_the_date_given(self, client, subject) -> None:
        measured_on = TODAY - timedelta(days=10)

        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, FIELD),
            json={"source": "measured", "as_of": str(measured_on)},
        )

        assert response.status_code == 200, response.text
        assert response.json()["as_of"] == str(measured_on)

    async def test_an_omitted_date_defaults_to_today(self, client, subject) -> None:
        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, FIELD), json={"source": "measured"}
        )

        assert response.json()["as_of"] == str(TODAY)

    async def test_confidence_crosses_the_wire_as_a_string(
        self, client, subject
    ) -> None:
        """Constitution IV reaches every figure, confidence included.

        A fraction between 0 and 1, which is what the column's CHECK holds --
        not a percentage. Sending 87.5 is a 422, not a row.
        """
        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, FIELD),
            json={"source": "measured", "confidence": "0.875"},
        )

        assert response.status_code == 200, response.text
        returned = response.json()["confidence"]
        # Compared as a Decimal, not as text: the column carries four decimal
        # places, so it comes back "0.8750". The trailing zero is the column's
        # scale and not a change in value -- which is exactly what a string
        # comparison would wrongly call a failure.
        assert isinstance(returned, str), "a figure must not cross the wire as a number"
        assert Decimal(returned) == Decimal("0.875")

    @pytest.mark.parametrize("value", ["87.5", "0", "-0.5", "1.5"])
    async def test_a_confidence_out_of_range_is_a_422_not_a_500(
        self, client, subject, value
    ) -> None:
        """Bounded in the schema as well as the column.

        Without the schema bound this reached the database and came back as an
        integrity error -- a 500 for what is a typo in a request body.
        """
        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, FIELD),
            json={"source": "measured", "confidence": value},
        )

        assert response.status_code == 422, response.text

    async def test_an_unknown_field_is_a_404(self, client, subject) -> None:
        """A typo would otherwise write a row nothing ever reads."""
        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, "print_time_minuets"),
            json={"source": "measured"},
        )

        assert response.status_code == 404, response.text

    async def test_an_unknown_source_is_refused(self, client, subject) -> None:
        response = await client.put(
            _write_url(ENTITY_TYPE, subject.id, FIELD), json={"source": "vibes"}
        )

        assert response.status_code == 422, response.text

    async def test_an_unauthenticated_read_is_refused(
        self, unauthenticated_client, subject
    ) -> None:
        response = await unauthenticated_client.get(_url(ENTITY_TYPE, subject.id))

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# FR-042e: a pending proposal is visible on the figure
# ---------------------------------------------------------------------------


class TestAPendingProposalIsVisible:
    @pytest_asyncio.fixture
    async def with_proposal(self, db_session, test_tenant, subject):
        decision = await consider_outcomes(
            db_session,
            test_tenant,
            subject,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=[
                Outcome(run_id=f"run-{index}", value=Decimal("900"), observed_on=TODAY)
                for index in range(3)
            ],
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )
        assert decision.proposal is not None
        await db_session.commit()
        return decision.proposal

    async def test_the_field_is_flagged(self, client, subject, with_proposal) -> None:
        """FR-042e. A divergence nobody is told about is one nobody acts on."""
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["has_pending_revision"] is True

    async def test_a_field_without_a_proposal_is_not_flagged(
        self, client, subject, with_proposal
    ) -> None:
        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()

        other = next(f for f in body["fields"] if f["field_name"] == "waste_grams")
        assert other["has_pending_revision"] is False

    async def test_the_figure_itself_has_not_moved(
        self, client, subject, with_proposal
    ) -> None:
        """Pricing keeps using the current estimate while a proposal is held."""
        assert subject.print_time_minutes == 100

    async def test_the_proposal_is_listed_with_everything_a_reviewer_needs(
        self, client, with_proposal
    ) -> None:
        body = (await client.get("/api/v1/estimate-revisions")).json()

        assert body["total"] == 1
        assert body["pending_count"] == 1
        proposal = body["revisions"][0]
        assert proposal["current_value"] == "100.000000"
        assert proposal["observed_value"] == "900.000000"
        assert Decimal(proposal["divergence_pct"]) == Decimal("800")
        assert sorted(proposal["derived_from_run_ids"]) == ["run-0", "run-1", "run-2"]
        assert proposal["state"] == "pending"

    async def test_every_figure_in_the_proposal_is_a_string(
        self, client, with_proposal
    ) -> None:
        """A JSON number is a float the moment anything parses it."""
        proposal = (await client.get("/api/v1/estimate-revisions")).json()["revisions"][0]

        for key in ("current_value", "observed_value", "divergence_pct"):
            assert isinstance(proposal[key], str), f"{key} crossed the wire as a number"

    async def test_the_list_can_be_filtered_by_state(
        self, client, with_proposal
    ) -> None:
        accepted = (
            await client.get("/api/v1/estimate-revisions?state=accepted")
        ).json()

        assert accepted["total"] == 0
        assert accepted["pending_count"] == 1, "the pending count is reported regardless"

    async def test_an_unknown_state_is_refused(self, client) -> None:
        response = await client.get("/api/v1/estimate-revisions?state=maybe")

        assert response.status_code == 422


class TestDecidingAProposalOverHttp:
    @pytest_asyncio.fixture
    async def held(self, db_session, test_tenant, subject):
        decision = await consider_outcomes(
            db_session,
            test_tenant,
            subject,
            entity_type=ENTITY_TYPE,
            field_name=FIELD,
            outcomes=[
                Outcome(run_id=f"run-{index}", value=Decimal("900"), observed_on=TODAY)
                for index in range(3)
            ],
            min_outcomes=3,
            divergence_threshold_pct=Decimal("25"),
        )
        await db_session.commit()
        return decision.proposal

    async def test_a_member_may_accept(self, as_role, held) -> None:
        async with as_role(UserRole.MEMBER) as client:
            response = await client.post(
                f"/api/v1/estimate-revisions/{held.id}/accept"
            )

        assert response.status_code == 200, response.text
        assert response.json()["state"] == "accepted"

    async def test_accepting_moves_the_figure(self, client, subject, held) -> None:
        response = await client.post(f"/api/v1/estimate-revisions/{held.id}/accept")

        assert response.status_code == 200, response.text
        assert subject.print_time_minutes == 900

    async def test_accepting_sets_the_origin_to_observed(
        self, client, subject, held
    ) -> None:
        await client.post(f"/api/v1/estimate-revisions/{held.id}/accept")

        body = (await client.get(_url(ENTITY_TYPE, subject.id))).json()
        entry = next(f for f in body["fields"] if f["field_name"] == FIELD)
        assert entry["source"] == "observed"
        assert entry["editable"] is False
        assert entry["has_pending_revision"] is False

    async def test_a_viewer_may_not_decide(self, as_role, held) -> None:
        async with as_role(UserRole.VIEWER) as client:
            response = await client.post(
                f"/api/v1/estimate-revisions/{held.id}/reject"
            )

        assert response.status_code == 403, response.text

    async def test_rejecting_leaves_the_figure_alone(
        self, client, subject, held
    ) -> None:
        response = await client.post(f"/api/v1/estimate-revisions/{held.id}/reject")

        assert response.status_code == 200, response.text
        assert subject.print_time_minutes == 100

    async def test_deciding_twice_is_a_conflict(self, client, held) -> None:
        await client.post(f"/api/v1/estimate-revisions/{held.id}/accept")

        again = await client.post(f"/api/v1/estimate-revisions/{held.id}/accept")

        assert again.status_code == 409, again.text

    async def test_a_proposal_that_is_not_this_tenants_is_a_404(
        self, client
    ) -> None:
        """404 rather than 403: a 403 confirms the id exists somewhere."""
        response = await client.post(f"/api/v1/estimate-revisions/{uuid4()}/accept")

        assert response.status_code == 404, response.text

    async def test_an_unauthenticated_decision_is_refused(
        self, unauthenticated_client, held
    ) -> None:
        response = await unauthenticated_client.post(
            f"/api/v1/estimate-revisions/{held.id}/accept"
        )

        assert response.status_code == 401
