"""`/shipping-profiles` — postage paid, kept apart from revenue (task T078a).

The requirement these exist to serve is FR-024's distinction: postage the
operator pays is not shipping revenue the customer was charged. The system had
nowhere to record the first, which is why free shipping looked free.

The one domain rule beyond ordinary validation is that two profiles for a zone
must not claim the same parcel: overlapping brackets would make an order's
postage depend on which row was read first. Gaps are allowed, because a
carrier's published table may have them and inventing postage for a weight the
operator has no price for would be worse than reporting none.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shipping_profile import ShippingProfile
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

URL = "/api/v1/shipping-profiles"


def _body(**overrides) -> dict:
    body = {
        "name": "Canada Post Expedited",
        "destination_zone": "domestic",
        "weight_bracket_min_grams": "0",
        "weight_bracket_max_grams": "250",
        "postage_cost": "9.50",
        "carrier": "Canada Post",
        "effective_from": "2026-01-01",
    }
    body.update(overrides)
    return body


async def _stored(db_session: AsyncSession) -> list[ShippingProfile]:
    result = await db_session.execute(select(ShippingProfile))
    return list(result.scalars().all())


# ============================================================================
# Creating
# ============================================================================


class TestCreatingAShippingProfile:
    async def test_an_admin_can_create_a_profile(self, client: AsyncClient) -> None:
        response = await client.post(URL, json=_body())

        assert response.status_code == 201
        body = response.json()
        assert Decimal(body["postage_cost"]) == Decimal("9.50")
        assert body["destination_zone"] == "domestic"

    async def test_an_open_ended_bracket_is_allowed(self, client: AsyncClient) -> None:
        """A carrier's top bracket often has no upper bound."""
        response = await client.post(
            URL,
            json=_body(
                name="Heavy parcels",
                weight_bracket_min_grams="2000",
                weight_bracket_max_grams=None,
            ),
        )

        assert response.status_code == 201
        assert response.json()["weight_bracket_max_grams"] is None

    async def test_adjacent_brackets_do_not_collide(self, client: AsyncClient) -> None:
        """0-250 and 250-500 is how carriers publish them, half-open above."""
        first = await client.post(URL, json=_body())
        assert first.status_code == 201

        second = await client.post(
            URL,
            json=_body(
                name="Canada Post Expedited heavy",
                weight_bracket_min_grams="250",
                weight_bracket_max_grams="500",
                postage_cost="12.75",
            ),
        )

        assert second.status_code == 201

    async def test_the_same_bracket_in_another_zone_is_allowed(self, client: AsyncClient) -> None:
        assert (await client.post(URL, json=_body())).status_code == 201

        response = await client.post(
            URL,
            json=_body(
                name="USPS to the US",
                destination_zone="us",
                postage_cost="18.40",
            ),
        )

        assert response.status_code == 201

    async def test_a_gap_between_brackets_is_allowed(self, client: AsyncClient) -> None:
        """A weight the operator has no published price for stays unpriced."""
        assert (await client.post(URL, json=_body())).status_code == 201

        response = await client.post(
            URL,
            json=_body(
                name="Canada Post Expedited heavy",
                weight_bracket_min_grams="1000",
                weight_bracket_max_grams="2000",
            ),
        )

        assert response.status_code == 201


class TestValidation:
    async def test_an_overlapping_bracket_is_a_422(self, client: AsyncClient) -> None:
        assert (await client.post(URL, json=_body())).status_code == 201

        response = await client.post(
            URL,
            json=_body(
                name="Overlapping",
                weight_bracket_min_grams="100",
                weight_bracket_max_grams="400",
            ),
        )

        assert response.status_code == 422
        assert "already covers" in str(response.json()["detail"])

    async def test_an_open_ended_bracket_overlapping_an_existing_one_is_a_422(
        self, client: AsyncClient
    ) -> None:
        assert (await client.post(URL, json=_body())).status_code == 201

        response = await client.post(
            URL,
            json=_body(
                name="Everything",
                weight_bracket_min_grams="0",
                weight_bracket_max_grams=None,
            ),
        )

        assert response.status_code == 422

    async def test_an_inverted_bracket_is_a_422(self, client: AsyncClient) -> None:
        response = await client.post(
            URL,
            json=_body(weight_bracket_min_grams="500", weight_bracket_max_grams="250"),
        )

        assert response.status_code == 422

    async def test_a_negative_postage_cost_is_a_422(self, client: AsyncClient) -> None:
        response = await client.post(URL, json=_body(postage_cost="-1.00"))

        assert response.status_code == 422

    async def test_a_missing_postage_cost_is_a_422(self, client: AsyncClient) -> None:
        body = _body()
        del body["postage_cost"]

        response = await client.post(URL, json=body)

        assert response.status_code == 422

    async def test_an_empty_zone_is_a_422(self, client: AsyncClient) -> None:
        response = await client.post(URL, json=_body(destination_zone=""))

        assert response.status_code == 422


# ============================================================================
# Reading
# ============================================================================


class TestReadingShippingProfiles:
    async def test_profiles_come_back_ordered_by_zone_then_bracket(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            URL,
            json=_body(
                name="Domestic heavy",
                weight_bracket_min_grams="250",
                weight_bracket_max_grams="500",
            ),
        )
        await client.post(URL, json=_body())
        await client.post(URL, json=_body(name="US", destination_zone="us"))

        body = (await client.get(URL)).json()

        assert body["total"] == 3
        assert [p["destination_zone"] for p in body["profiles"]] == [
            "domestic",
            "domestic",
            "us",
        ]
        assert [Decimal(p["weight_bracket_min_grams"]) for p in body["profiles"][:2]] == [
            Decimal("0"),
            Decimal("250"),
        ]

    async def test_a_zone_filter_narrows_the_list(self, client: AsyncClient) -> None:
        await client.post(URL, json=_body())
        await client.post(URL, json=_body(name="US", destination_zone="us"))

        body = (await client.get(URL, params={"destination_zone": "us"})).json()

        assert body["total"] == 1
        assert body["profiles"][0]["destination_zone"] == "us"

    async def test_one_profile_can_be_read_by_id(self, client: AsyncClient) -> None:
        created = (await client.post(URL, json=_body())).json()

        response = await client.get(f"{URL}/{created['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    async def test_an_unknown_profile_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(f"{URL}/{uuid4()}")

        assert response.status_code == 404

    async def test_an_unauthenticated_read_is_a_401(
        self, unauthenticated_client: AsyncClient
    ) -> None:
        response = await unauthenticated_client.get(URL)

        assert response.status_code == 401

    async def test_a_viewer_may_read(self, client: AsyncClient, as_role) -> None:
        """FR-007c: postage is part of a margin a viewer can see."""
        await client.post(URL, json=_body())

        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.get(URL)

        assert response.status_code == 200
        assert response.json()["total"] == 1


# ============================================================================
# Updating and deleting
# ============================================================================


class TestUpdatingAShippingProfile:
    async def test_the_postage_can_be_changed(self, client: AsyncClient) -> None:
        """Carriers reprice annually, which is what `effective_from` is for."""
        created = (await client.post(URL, json=_body())).json()

        response = await client.put(
            f"{URL}/{created['id']}",
            json={"postage_cost": "10.25", "effective_from": "2027-01-01"},
        )

        assert response.status_code == 200
        assert Decimal(response.json()["postage_cost"]) == Decimal("10.25")

    async def test_fields_the_body_omits_are_left_alone(self, client: AsyncClient) -> None:
        created = (await client.post(URL, json=_body())).json()

        updated = (
            await client.put(f"{URL}/{created['id']}", json={"postage_cost": "10.25"})
        ).json()

        assert updated["carrier"] == "Canada Post"
        assert Decimal(updated["weight_bracket_max_grams"]) == Decimal("250")

    async def test_an_update_into_an_existing_bracket_is_a_422(self, client: AsyncClient) -> None:
        first = (await client.post(URL, json=_body())).json()
        second = (
            await client.post(
                URL,
                json=_body(
                    name="Heavy",
                    weight_bracket_min_grams="250",
                    weight_bracket_max_grams="500",
                ),
            )
        ).json()
        del first

        response = await client.put(
            f"{URL}/{second['id']}", json={"weight_bracket_min_grams": "100"}
        )

        assert response.status_code == 422

    async def test_an_update_that_inverts_the_bracket_is_a_422(self, client: AsyncClient) -> None:
        created = (await client.post(URL, json=_body())).json()

        response = await client.put(
            f"{URL}/{created['id']}", json={"weight_bracket_min_grams": "500"}
        )

        assert response.status_code == 422

    async def test_an_unknown_profile_is_a_404(self, client: AsyncClient) -> None:
        response = await client.put(f"{URL}/{uuid4()}", json={"postage_cost": "1.00"})

        assert response.status_code == 404

    async def test_a_member_is_refused_and_the_figure_is_untouched(
        self, client: AsyncClient, db_session: AsyncSession, as_role
    ) -> None:
        """FR-007a and FR-007d."""
        created = (await client.post(URL, json=_body())).json()

        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(f"{URL}/{created['id']}", json={"postage_cost": "0.01"})

        assert response.status_code == 403
        stored = await _stored(db_session)
        assert Decimal(str(stored[0].postage_cost)) == Decimal("9.50")

    async def test_a_member_is_refused_a_create(self, client: AsyncClient, as_role) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(URL, json=_body())

        assert response.status_code == 403


class TestDeletingAShippingProfile:
    async def test_an_admin_can_delete_a_profile(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        created = (await client.post(URL, json=_body())).json()

        response = await client.delete(f"{URL}/{created['id']}")

        assert response.status_code == 204
        assert await _stored(db_session) == []

    async def test_an_unknown_profile_is_a_404(self, client: AsyncClient) -> None:
        response = await client.delete(f"{URL}/{uuid4()}")

        assert response.status_code == 404

    async def test_a_member_is_refused_a_delete(
        self, client: AsyncClient, db_session: AsyncSession, as_role
    ) -> None:
        created = (await client.post(URL, json=_body())).json()

        async with as_role(UserRole.MEMBER) as member:
            response = await member.delete(f"{URL}/{created['id']}")

        assert response.status_code == 403
        assert len(await _stored(db_session)) == 1


# ============================================================================
# The bracket lookup the margin path uses
# ============================================================================


class TestTheBracketLookup:
    async def test_a_parcel_on_a_boundary_belongs_to_the_upper_bracket(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Inclusive below, exclusive above, so 250 g is not in 0-250."""
        await client.post(URL, json=_body())
        await client.post(
            URL,
            json=_body(
                name="Heavy",
                weight_bracket_min_grams="250",
                weight_bracket_max_grams="500",
                postage_cost="12.75",
            ),
        )

        stored = sorted(await _stored(db_session), key=lambda p: p.weight_bracket_min_grams)
        light, heavy = stored

        assert light.covers(Decimal("249.99")) is True
        assert light.covers(Decimal("250")) is False
        assert heavy.covers(Decimal("250")) is True

    async def test_an_open_ended_bracket_covers_any_heavier_parcel(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await client.post(
            URL,
            json=_body(weight_bracket_min_grams="2000", weight_bracket_max_grams=None),
        )

        profile = (await _stored(db_session))[0]

        assert profile.covers(Decimal("50000")) is True
        assert profile.covers(Decimal("1999")) is False
