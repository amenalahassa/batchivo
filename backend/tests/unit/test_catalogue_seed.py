"""The catalogue seeding service: packaging and carrier postage (T008, T022, T034, T037)."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.models.consumable import ConsumableType
from app.models.order import Order
from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from app.services import catalogue_data as cd
from app.services import catalogue_seed as seed
from app.services.provenance import origins_for_entity

TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    cd.clear_caches()
    yield
    cd.clear_caches()


async def _shop(db, tenant, currency="CAD", country=None):
    tenant.currency_code = currency
    tenant.country_code = country
    tenant.settings = {}
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def _packaging(db, tenant) -> list[ConsumableType]:
    return list(
        (
            await db.execute(
                select(ConsumableType).where(
                    ConsumableType.tenant_id == tenant.id,
                    ConsumableType.packaging_kind.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )


async def _profiles(db, tenant) -> list[ShippingProfile]:
    return list(
        (await db.execute(select(ShippingProfile).where(ShippingProfile.tenant_id == tenant.id)))
        .scalars()
        .all()
    )


def _bracket_count(tariff, services=None) -> int:
    return sum(
        len(zone.brackets)
        for service in tariff.services
        if services is None or service.key in services
        for zone in service.zones
    )


# ============================================
# Notices (T008)
# ============================================


class TestNotices:
    async def test_round_trip(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        result = seed.SeedResult(part="packaging", version=1, added=[{"key": "a", "id": None}])
        await seed.record_notice(db_session, tenant, "packaging", result)
        await db_session.commit()
        notice = seed.pending_notices(tenant)["packaging"]
        assert notice["added"] == ["a"] and notice["acknowledged"] is False
        await seed.acknowledge(db_session, tenant, "packaging")
        await db_session.refresh(tenant)
        assert seed.pending_notices(tenant) == {}
        assert seed.seed_state(tenant, "packaging")["acknowledged"] is True

    async def test_unknown_part_is_refused(self, db_session, test_tenant):
        with pytest.raises(seed.CatalogueSeedError):
            await seed.acknowledge(db_session, test_tenant, "labels")  # type: ignore[arg-type]

    async def test_acknowledging_nothing_is_harmless(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.acknowledge(db_session, tenant, "postage")
        assert seed.pending_notices(tenant) == {}


# ============================================
# Packaging (T022)
# ============================================


class TestSeedPackaging:
    async def test_seeds_every_item_with_its_key_and_version(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        catalogue = cd.load_packaging_catalogue()
        result = await seed.seed_packaging(db_session, tenant)
        await db_session.commit()
        rows = await _packaging(db_session, tenant)
        assert len(result.added) == len(catalogue.items) == len(rows)
        assert {r.catalogue_key for r in rows} == set(catalogue.by_key())
        assert all(r.catalogue_version == catalogue.version for r in rows)

    async def test_every_figure_is_assumed_and_dated_by_the_catalogue(
        self, db_session, test_tenant
    ):
        tenant = await _shop(db_session, test_tenant)
        catalogue = cd.load_packaging_catalogue()
        await seed.seed_packaging(db_session, tenant)
        await db_session.commit()
        rows = {r.catalogue_key: r for r in await _packaging(db_session, tenant)}
        box = rows["box-cube-100"]
        origins = await origins_for_entity(db_session, tenant, "consumable_type", box.id)
        for name in ("inner_length_mm", "wall_mm", "empty_weight_grams", "current_cost_per_unit"):
            assert origins[name].source == "assumed"
            assert origins[name].as_of == catalogue.as_of
            assert origins[name].is_default is False
        fill = await origins_for_entity(
            db_session, tenant, "consumable_type", rows["void-kraft-paper"].id
        )
        assert fill["fill_volume_ml"].source == "assumed" and not fill["fill_volume_ml"].is_default

    async def test_cost_comes_from_the_tenant_currency(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant, currency="GBP")
        await seed.seed_packaging(db_session, tenant, ["box-cube-100"])
        await db_session.commit()
        (row,) = await _packaging(db_session, tenant)
        item = cd.load_packaging_catalogue().by_key()["box-cube-100"]
        assert row.current_cost_per_unit == item.typical_cost["GBP"]

    async def test_a_currency_without_a_typical_cost_seeds_no_cost(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant, currency="AUD")
        await seed.seed_packaging(db_session, tenant, ["box-cube-100"])
        await db_session.commit()
        (row,) = await _packaging(db_session, tenant)
        assert row.current_cost_per_unit is None
        origins = await origins_for_entity(db_session, tenant, "consumable_type", row.id)
        assert origins["current_cost_per_unit"].is_default  # nothing recorded for no figure

    async def test_second_run_adds_nothing(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_packaging(db_session, tenant)
        await db_session.commit()
        again = await seed.seed_packaging(db_session, tenant)
        await db_session.commit()
        assert again.added == []
        assert {s["reason"] for s in again.skipped} == {seed.ALREADY_PRESENT}
        assert len(await _packaging(db_session, tenant)) == len(cd.load_packaging_catalogue().items)

    async def test_an_operator_item_of_the_same_kind_and_name_is_kept(
        self, db_session, test_tenant
    ):
        tenant = await _shop(db_session, test_tenant)
        mine = ConsumableType(
            tenant_id=tenant.id,
            sku="MY-BOX",
            name="box cube 100 × 100 × 100 MM",
            packaging_kind="box",
            inner_length_mm=Decimal("101"),
            inner_width_mm=Decimal("101"),
            inner_height_mm=Decimal("101"),
            current_cost_per_unit=Decimal("2.00"),
        )
        db_session.add(mine)
        await db_session.commit()
        result = await seed.seed_packaging(db_session, tenant, ["box-cube-100", "box-cube-150"])
        await db_session.commit()
        assert {"key": "box-cube-100", "reason": seed.NAME_IN_USE} in result.skipped
        assert [a["key"] for a in result.added] == ["box-cube-150"]
        await db_session.refresh(mine)
        assert mine.inner_length_mm == Decimal("101") and mine.catalogue_key is None
        assert mine.current_cost_per_unit == Decimal("2.00")

    async def test_a_deleted_item_returns_only_on_explicit_apply(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_packaging(db_session, tenant, release=True)
        await db_session.commit()
        rows = {r.catalogue_key: r for r in await _packaging(db_session, tenant)}
        await db_session.delete(rows["box-cube-100"])
        await db_session.commit()

        release = await seed.seed_packaging(db_session, tenant, release=True)
        await db_session.commit()
        assert release.not_due and release.added == []

        explicit = await seed.seed_packaging(db_session, tenant, ["box-cube-100"])
        await db_session.commit()
        assert [a["key"] for a in explicit.added] == ["box-cube-100"]

    async def test_release_after_a_catalogue_bump_skips_removed_keys(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_packaging(db_session, tenant, ["box-cube-100"], release=True)
        await db_session.commit()
        (row,) = await _packaging(db_session, tenant)
        await db_session.delete(row)
        state = seed.seed_state(tenant, "packaging")
        state["version"] = 0  # an older catalogue was applied
        await seed._write_seed_part(db_session, tenant, "packaging", state)
        await db_session.commit()
        result = await seed.seed_packaging(db_session, tenant, release=True)
        await db_session.commit()
        assert "box-cube-100" not in {a["key"] for a in result.added}
        assert len(result.added) == len(cd.load_packaging_catalogue().items) - 1

    async def test_seeding_never_changes_a_products_accepted_packaging(
        self, db_session, test_tenant
    ):
        tenant = await _shop(db_session, test_tenant)
        mine = ConsumableType(
            tenant_id=tenant.id, sku="MAILER", name="Mine", packaging_kind="mailer"
        )
        db_session.add(mine)
        await db_session.flush()
        product = Product(
            tenant_id=tenant.id, sku="P-1", name="Dragon", packaging_consumable_id=mine.id
        )
        db_session.add(product)
        await db_session.commit()
        await seed.seed_packaging(db_session, tenant)
        await db_session.commit()
        await db_session.refresh(product)
        assert product.packaging_consumable_id == mine.id

    async def test_unknown_key_is_refused(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        with pytest.raises(seed.UnknownCatalogueKey):
            await seed.seed_packaging(db_session, tenant, ["box-cube-100", "box-nope"])
        assert await _packaging(db_session, tenant) == []

    async def test_a_failure_leaves_nothing(self, db_session, test_tenant, monkeypatch):
        tenant = await _shop(db_session, test_tenant)

        async def broken(*args, **kwargs):
            raise RuntimeError("notice store down")

        monkeypatch.setattr(seed, "record_notice", broken)
        with pytest.raises(RuntimeError):
            await seed.seed_packaging(db_session, tenant)
        await db_session.commit()
        assert await _packaging(db_session, tenant) == []
        await db_session.refresh(tenant)
        assert seed.seed_state(tenant, "packaging") == {}

    async def test_notice_lists_added_and_skipped(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_packaging(db_session, tenant, ["box-cube-100"])
        await seed.seed_packaging(db_session, tenant, ["box-cube-100", "box-cube-150"])
        await db_session.commit()
        notice = seed.pending_notices(tenant)["packaging"]
        assert notice["added"] == ["box-cube-150"]
        assert notice["skipped"] == [{"key": "box-cube-100", "reason": seed.ALREADY_PRESENT}]
        assert set(notice["seeded_keys"]) == {"box-cube-100", "box-cube-150"}


# ============================================
# Postage (T034, T037)
# ============================================


def _write_tariff(root: Path, carrier: str, effective: str, price: str) -> None:
    folder = root / carrier
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "carrier": carrier,
        "name": cd.CARRIER_NAMES[carrier],
        "currency": cd.CARRIER_CURRENCY[carrier],
        "effective_date": effective,
        "source": f"test tariff {effective}",
        "services": [
            {
                "key": "small_packet",
                "name": "Small Packet",
                "max_length_mm": "400",
                "max_width_mm": "300",
                "max_height_mm": "200",
                "zones": [
                    {
                        "zone": "us",
                        "brackets": [
                            {"min_grams": "0", "max_grams": "500", "price": price},
                            {"min_grams": "500", "max_grams": "2000", "price": "20.00"},
                        ],
                    }
                ],
            },
            {
                "key": "expedited_parcel",
                "name": "Expedited Parcel",
                "zones": [
                    {
                        "zone": "us",
                        "brackets": [{"min_grams": "0", "max_grams": None, "price": "25.00"}],
                    }
                ],
            },
        ],
    }
    (folder / f"{effective}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def two_tariffs(tmp_path, monkeypatch):
    _write_tariff(tmp_path, "canada_post", "2026-01-12", "9.00")
    _write_tariff(tmp_path, "canada_post", "2027-01-11", "9.50")
    _write_tariff(tmp_path, "usps", "2026-10-04", "7.00")
    monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
    cd.clear_caches()


class TestSeedPostage:
    async def test_one_profile_per_service_zone_and_bracket(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        tariff = cd.latest_tariff("canada_post")
        result = await seed.seed_postage(db_session, tenant)
        await db_session.commit()
        rows = await _profiles(db_session, tenant)
        assert len(rows) == len(result.added) == _bracket_count(tariff)
        assert result.carrier == "canada_post" and result.chosen_from == "currency"
        for row in rows:
            assert row.catalogue_carrier == "canada_post"
            assert row.service in cd.CARRIER_SERVICES["canada_post"]
            assert row.tariff_version == tariff.effective_date
            assert row.source == tariff.source
        origins = await origins_for_entity(db_session, tenant, "shipping_profile", rows[0].id)
        assert origins["postage_cost"].source == "assumed"
        assert origins["postage_cost"].as_of == tariff.effective_date

    async def test_selected_services_only(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        tariff = cd.latest_tariff("canada_post")
        await seed.seed_postage(db_session, tenant, "canada_post", ["small_packet"])
        await db_session.commit()
        rows = await _profiles(db_session, tenant)
        assert {r.service for r in rows} == {"small_packet"}
        assert len(rows) == _bracket_count(tariff, {"small_packet"})
        assert tenant.settings["postage"]["carrier"] == "canada_post"

    async def test_an_overlapping_bracket_is_skipped_and_the_operator_row_kept(
        self, db_session, test_tenant
    ):
        tenant = await _shop(db_session, test_tenant)
        mine = ShippingProfile(
            tenant_id=tenant.id,
            name="My Lettermail",
            destination_zone="domestic",
            weight_bracket_min_grams=Decimal("0"),
            weight_bracket_max_grams=Decimal("1000"),
            postage_cost=Decimal("3.00"),
            effective_from=date(2026, 1, 1),
            max_length_mm=Decimal("380"),
            max_width_mm=Decimal("270"),
            max_height_mm=Decimal("20"),
        )
        db_session.add(mine)
        await db_session.commit()
        result = await seed.seed_postage(db_session, tenant)
        await db_session.commit()
        skipped = [s for s in result.skipped if s["service"] == "lettermail"]
        assert skipped and {s["reason"] for s in skipped} == {seed.OVERLAPS_EXISTING}
        await db_session.refresh(mine)
        assert mine.postage_cost == Decimal("3.00") and mine.effective_to is None

    async def test_seeding_twice_adds_nothing(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        first = await seed.seed_postage(db_session, tenant)
        await db_session.commit()
        again = await seed.seed_postage(db_session, tenant)
        await db_session.commit()
        assert again.added == [] and again.superseded == 0
        assert {s["reason"] for s in again.skipped} == {seed.ALREADY_PRESENT}
        assert len(await _profiles(db_session, tenant)) == len(first.added)

    @pytest.mark.parametrize(
        ("currency", "country", "reason"),
        [
            ("AUD", None, cd.NO_CARRIER_FOR_CURRENCY),
            ("EUR", "BE", cd.NO_CARRIER_FOR_COUNTRY),
            ("USD", "CA", cd.CARRIER_CURRENCY_MISMATCH),
        ],
    )
    async def test_no_carrier_seeds_nothing_and_says_why(
        self, db_session, test_tenant, currency, country, reason
    ):
        tenant = await _shop(db_session, test_tenant, currency=currency, country=country)
        result = await seed.seed_postage(db_session, tenant, release=True)
        await db_session.commit()
        assert result.reason == reason and result.added == []
        assert await _profiles(db_session, tenant) == []
        notice = seed.pending_notices(tenant)["postage"]
        assert notice["reason"] == reason and notice["carrier"] is None

    async def test_country_chooses_before_currency(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant, currency="EUR", country="FR")
        result = await seed.seed_postage(db_session, tenant, release=True)
        await db_session.commit()
        assert (result.carrier, result.chosen_from) == ("la_poste", "country")

    async def test_release_skips_a_tenant_seeded_before(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_postage(db_session, tenant, release=True)
        await db_session.commit()
        again = await seed.seed_postage(db_session, tenant, release=True)
        assert again.not_due

    async def test_explicit_carrier_errors(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        with pytest.raises(seed.UnknownCarrier):
            await seed.seed_postage(db_session, tenant, "pigeon_post")
        with pytest.raises(seed.CarrierCurrencyMismatch):
            await seed.seed_postage(db_session, tenant, "usps")
        with pytest.raises(seed.UnknownService):
            await seed.seed_postage(db_session, tenant, "canada_post", ["teleport"])
        with pytest.raises(seed.TariffNotFound):
            await seed.seed_postage(db_session, tenant, "canada_post", None, date(2001, 1, 1))

    @pytest.mark.usefixtures("two_tariffs")
    async def test_a_newer_tariff_is_offered_then_supersedes(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_postage(db_session, tenant, "canada_post", None, date(2026, 1, 12))
        await db_session.commit()
        old_rows = await _profiles(db_session, tenant)

        (update,) = await seed.pending_tariff_updates(db_session, tenant)
        assert (update.carrier, update.current, update.latest) == (
            "canada_post",
            date(2026, 1, 12),
            date(2027, 1, 11),
        )
        # Nothing changes until accepted.
        assert all(r.effective_to is None for r in old_rows)

        result = await seed.seed_postage(db_session, tenant, "canada_post")
        await db_session.commit()
        assert result.superseded == len(old_rows)
        for row in old_rows:
            await db_session.refresh(row)
            assert row.effective_to == date(2027, 1, 10)
            assert row.postage_cost in (Decimal("9.00"), Decimal("20.00"), Decimal("25.00"))
        new = [
            r for r in await _profiles(db_session, tenant) if r.tariff_version == date(2027, 1, 11)
        ]
        assert len(new) == len(old_rows)
        assert all(r.effective_from == date(2027, 1, 11) for r in new)
        assert await seed.pending_tariff_updates(db_session, tenant) == []

    @pytest.mark.usefixtures("two_tariffs")
    async def test_switching_carrier_supersedes_seeded_rows_only(
        self, db_session, test_tenant, monkeypatch
    ):
        tenant = await _shop(db_session, test_tenant)
        mine = ShippingProfile(
            tenant_id=tenant.id,
            name="Courier",
            destination_zone="local",
            weight_bracket_min_grams=Decimal("0"),
            postage_cost=Decimal("4.00"),
            effective_from=date(2026, 1, 1),
        )
        db_session.add(mine)
        await seed.seed_postage(db_session, tenant, "canada_post", None, date(2026, 1, 12))
        await db_session.commit()
        later = TODAY + timedelta(days=10)
        monkeypatch.setattr(clock, "today", lambda: later)
        tenant.currency_code = "USD"
        await db_session.commit()
        result = await seed.seed_postage(db_session, tenant, "usps")
        await db_session.commit()
        assert result.superseded > 0
        rows = await _profiles(db_session, tenant)
        canada = [r for r in rows if r.catalogue_carrier == "canada_post"]
        assert canada and all(r.effective_to == later - timedelta(days=1) for r in canada)
        await db_session.refresh(mine)
        assert mine.effective_to is None
        assert tenant.settings["postage"]["carrier"] == "usps"

    async def test_default_service_is_kept_only_while_priced(self, db_session, test_tenant):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_postage(db_session, tenant, default_service="canada_post:small_packet")
        await db_session.commit()
        assert tenant.settings["postage"]["default_service"] == "canada_post:small_packet"
        await seed.remove_postage_service(db_session, tenant, "small_packet")
        await db_session.commit()
        assert tenant.settings["postage"]["default_service"] is None

    async def test_removing_a_service_supersedes_its_seeded_rows(
        self, db_session, test_tenant, monkeypatch
    ):
        tenant = await _shop(db_session, test_tenant)
        await seed.seed_postage(db_session, tenant)
        await db_session.commit()
        later = TODAY + timedelta(days=3)
        monkeypatch.setattr(clock, "today", lambda: later)
        closed = await seed.remove_postage_service(db_session, tenant, "canada_post:lettermail")
        await db_session.commit()
        rows = [r for r in await _profiles(db_session, tenant) if r.service == "lettermail"]
        assert closed == len(rows) > 0
        assert all(r.effective_to == later - timedelta(days=1) for r in rows)
        assert "canada_post:lettermail" not in await seed.services_in_force(db_session, tenant)
        with pytest.raises(seed.ServiceNotSeeded):
            await seed.remove_postage_service(db_session, tenant, "lettermail")

    @pytest.mark.usefixtures("two_tariffs")
    async def test_a_frozen_order_keeps_its_postage_after_a_supersede(
        self, db_session, test_tenant
    ):
        from app.services.postage import freeze_order_postage

        tenant = await _shop(db_session, test_tenant)
        await seed.seed_postage(db_session, tenant, "canada_post", None, date(2026, 1, 12))
        await db_session.commit()
        product = Product(tenant_id=tenant.id, sku="P-W", name="Widget", weight_grams=300)
        db_session.add(product)
        order = Order(
            tenant_id=tenant.id,
            order_number=f"T-{uuid4().hex[:6]}",
            status="pending",
            customer_email="c@example.com",
            customer_name="C",
            shipping_address_line1="1 St",
            shipping_city="City",
            shipping_postcode="00000",
            shipping_country="us",
            shipping_method="Post",
            shipping_cost=Decimal("0"),
            subtotal=Decimal("10"),
            total=Decimal("10"),
            currency="CAD",
            payment_provider="test",
            payment_status="completed",
        )
        db_session.add(order)
        await db_session.flush()
        frozen = await freeze_order_postage(db_session, tenant, order, [(product, 1)])
        await db_session.commit()
        assert frozen.amount == Decimal("25.00")

        await seed.seed_postage(db_session, tenant, "canada_post")
        await db_session.commit()
        await db_session.refresh(order)
        assert order.postage_paid == Decimal("25.00")

    async def test_postage_failure_leaves_nothing(self, db_session, test_tenant, monkeypatch):
        tenant = await _shop(db_session, test_tenant)

        async def broken(*args, **kwargs):
            raise RuntimeError("boom")

        tenant_id = tenant.id  # the rolled-back savepoint expires the tenant
        monkeypatch.setattr(seed, "record_notice", broken)
        with pytest.raises(RuntimeError):
            await seed.seed_postage(db_session, tenant)
        await db_session.commit()
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(ShippingProfile)
                .where(ShippingProfile.tenant_id == tenant_id)
            )
        ).scalar_one()
        assert count == 0
        await db_session.refresh(tenant)
        assert "postage" not in (tenant.settings or {})
