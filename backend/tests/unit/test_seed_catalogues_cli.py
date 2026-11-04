"""The release step that seeds catalogues for existing shops (spec 006, T054-T056)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli import seed_catalogues as cli
from app.core import clock
from app.models.consumable import ConsumableType
from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from app.models.tenant import Tenant
from app.services import catalogue_data as cd
from app.services import catalogue_seed


TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    cd.clear_caches()
    yield
    cd.clear_caches()


@pytest.fixture
def factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _shops(db_session, *slugs: str) -> list[Tenant]:
    shops = [
        Tenant(id=uuid4(), name=s, slug=s, settings={}, currency_code="CAD", is_active=True)
        for s in slugs
    ]
    db_session.add_all(shops)
    await db_session.commit()
    return shops


async def _count(db_session, model, tenant) -> int:
    # The identity, not ``tenant.id``: the row may be expired by now.
    tenant_id = inspect(tenant).identity[0]
    db_session.expire_all()
    return (
        await db_session.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
class TestRun:
    async def test_every_tenant_is_seeded_once(self, factory, db_session):
        shops = await _shops(db_session, "shop-a", "shop-b")
        summary = await cli.run(factory)
        assert not summary.locked_out and summary.failures == 0
        total = len(cd.load_packaging_catalogue().items)
        for shop in shops:
            assert await _count(db_session, ConsumableType, shop) == total
            assert await _count(db_session, ShippingProfile, shop) > 0
        by_slug = {t.slug: t for t in summary.tenants}
        assert by_slug["shop-a"].packaging.startswith(f"{total} added")
        assert by_slug["shop-a"].postage.startswith("canada_post:")

    async def test_a_second_run_is_a_no_op(self, factory, db_session):
        (shop,) = await _shops(db_session, "shop-a")
        await cli.run(factory)
        before = await _count(db_session, ShippingProfile, shop)
        again = await cli.run(factory)
        assert [(t.packaging, t.postage) for t in again.tenants] == [
            ("nothing to do", "nothing to do")
        ]
        assert "nothing to do" in again.render()
        assert await _count(db_session, ShippingProfile, shop) == before

    async def test_one_tenant_only(self, factory, db_session):
        a, b = await _shops(db_session, "shop-a", "shop-b")
        summary = await cli.run(factory, tenant_slug="shop-b")
        assert [t.slug for t in summary.tenants] == ["shop-b"]
        assert await _count(db_session, ConsumableType, a) == 0
        assert await _count(db_session, ConsumableType, b) > 0

    async def test_an_inactive_tenant_is_left_alone(self, factory, db_session):
        (shop,) = await _shops(db_session, "shop-a")
        shop.is_active = False
        await db_session.commit()
        summary = await cli.run(factory)
        assert summary.tenants == [] and summary.render() == "no tenants"

    async def test_a_tenant_without_a_carrier_reports_why(self, factory, db_session):
        (shop,) = await _shops(db_session, "shop-a")
        shop.currency_code = "AUD"
        await db_session.commit()
        (outcome,) = (await cli.run(factory)).tenants
        assert outcome.error is None and outcome.postage.startswith("none (")
        assert await _count(db_session, ShippingProfile, shop) == 0

    async def test_a_failing_tenant_does_not_stop_the_others(
        self, factory, db_session, monkeypatch
    ):
        bad, good = await _shops(db_session, "shop-a", "shop-b")
        real = catalogue_seed.seed_packaging

        async def flaky(db, tenant, *args, **kwargs):
            if tenant.slug == "shop-a":
                await real(db, tenant, *args, **kwargs)  # half-written, then fails
                raise RuntimeError("disk on fire")
            return await real(db, tenant, *args, **kwargs)

        monkeypatch.setattr(catalogue_seed, "seed_packaging", flaky)
        summary = await cli.run(factory)
        outcomes = {t.slug: t for t in summary.tenants}
        assert outcomes["shop-a"].error == "disk on fire" and summary.failures == 1
        assert outcomes["shop-b"].error is None
        assert await _count(db_session, ConsumableType, bad) == 0  # rolled back
        assert await _count(db_session, ConsumableType, good) > 0
        assert "FAILED: disk on fire" in summary.render()

    async def test_the_lock_keeps_a_second_run_out(self, factory, db_engine, db_session):
        await _shops(db_session, "shop-a")
        async with db_engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": cli.LOCK_KEY})
            try:
                summary = await cli.run(factory)
            finally:
                await holder.rollback()
        assert summary.locked_out and summary.tenants == []
        assert "holds the lock" in summary.render()
        # Released: the next run goes ahead.
        assert not (await cli.run(factory)).locked_out


@pytest.mark.asyncio
class TestDryRun:
    async def test_writes_nothing_and_reports(self, factory, db_session):
        (shop,) = await _shops(db_session, "shop-a")
        db_session.add(
            Product(
                tenant_id=inspect(shop).identity[0],
                sku="DRAGON",
                name="Dragon",
                is_active=True,
                weight_grams=Decimal("120"),
            )
        )
        await db_session.commit()
        summary = await cli.run(factory, dry_run=True)
        assert await _count(db_session, ConsumableType, shop) == 0
        assert await _count(db_session, ShippingProfile, shop) == 0
        db_session.expire_all()
        refreshed = await db_session.get(Tenant, inspect(shop).identity[0])
        assert "catalogue_seed" not in (refreshed.settings or {})
        report = cli.render_report(summary, TODAY)
        assert "| shop-a |" in report and "rolled back" in report
        assert "Postage per product and zone" in report


class TestDeltaRows:
    def test_only_changes_are_listed(self):
        from app.services.postage import Postage

        before = {
            ("A", "us"): Postage(amount=None, reason="no_profile"),
            ("B", "us"): Postage(amount=Decimal("5.00")),
        }
        after = {
            ("A", "us"): Postage(amount=Decimal("9.10"), notes=("no_packaging_recorded",)),
            ("B", "us"): Postage(amount=Decimal("5.00")),
            ("C", "us"): Postage(amount=Decimal("4.00")),
        }
        rows = cli.delta_rows("shop", before, after)
        assert [(r["sku"], r["before"], r["after"], r["difference"]) for r in rows] == [
            ("A", None, Decimal("9.10"), None),
            ("C", None, Decimal("4.00"), None),
        ]
        assert rows[0]["note"] == "no_packaging_recorded"

    def test_difference_when_both_known(self):
        from app.services.postage import Postage

        rows = cli.delta_rows(
            "shop",
            {("A", "us"): Postage(amount=Decimal("5.00"))},
            {("A", "us"): Postage(amount=Decimal("6.25"))},
        )
        assert rows[0]["difference"] == Decimal("1.25")


class TestMain:
    def test_report_needs_dry_run(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["--all-tenants", "--report", "x.md"])

    def test_a_scope_is_required(self):
        with pytest.raises(SystemExit):
            cli.main([])

    def test_windows_runs_on_a_selector_loop(self, monkeypatch):
        """psycopg's async mode cannot run on Windows' default Proactor loop."""
        import asyncio

        monkeypatch.setattr(cli.sys, "platform", "win32")
        assert cli.event_loop_factory() is asyncio.SelectorEventLoop

    def test_other_platforms_keep_the_default_loop(self, monkeypatch):
        monkeypatch.setattr(cli.sys, "platform", "linux")
        assert cli.event_loop_factory() is None
