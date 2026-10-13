"""Exchange rates, and what happens when the outside world does not help (T092).

Five of FR-028's clauses are rules about failure, so most of this file is about
what the service does when it cannot get what it asked for:

* **FR-028f** — fetch once per day per pair and reuse. Forty sales on one day
  are one request and one rate, not forty of each.
* **FR-028g** — an unreachable service falls back to the last known rate, and
  the day that rate came from travels with it.
* **FR-028h** — a hand-entered rate overrides the fetched one.
* **FR-028i** — a sale is never blocked by rate-service unavailability.
* **FR-028j** — a rate frozen onto an order is never revised, not even when a
  better one becomes known the next day.

And the one that is not about failure but matters most: **a pair with no rate
on record returns ``None``, never ``1.0``**. Implying parity makes a
cross-currency sale look like a same-currency one, and nothing on screen would
show the difference until someone reconciled a bank statement. There is a test
below whose only job is to fail if somebody "simplifies" that into a default.

The provider is reached through the ``RateProvider`` protocol, so day reuse,
stale fallback and the never-fetched pair are all exercised without a network.
``respx`` is used only for :class:`HttpRateProvider`, which is the one piece
that genuinely speaks HTTP.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx
import pytest
import respx

from app.core import clock
from app.models.fx_rate import FxRate
from app.services import fx_service
from app.services.fx_service import (
    HttpRateProvider,
    RateUnavailableError,
    latest_known_rate,
    record_rate,
    require_rate,
    resolve_rate,
    set_manual_rate,
)

TODAY = clock.today()
YESTERDAY = TODAY - timedelta(days=1)
LAST_MONTH = TODAY - timedelta(days=30)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class CountingProvider:
    """A provider that answers with a fixed rate and counts being asked.

    The count is the point: FR-028f is a statement about how many times the
    service is called, which no assertion on the returned rate can check.
    """

    def __init__(self, rate: Optional[str] = "1.74", *, fails: bool = False):
        self.rate = Decimal(rate) if rate is not None else None
        self.fails = fails
        self.calls: list[tuple[str, str]] = []

    async def fetch(self, base: str, quote: str) -> Optional[Decimal]:
        self.calls.append((base, quote))
        if self.fails:
            # Returns None rather than raising, which is what the protocol
            # requires of an ordinary outage.
            return None
        return self.rate

    @property
    def call_count(self) -> int:
        return len(self.calls)


class ExplodingProvider:
    """A provider that raises, i.e. one that breaks the protocol's contract.

    Used to pin down which callers are protected from a badly behaved provider
    and which are not, rather than leaving it to chance.
    """

    def __init__(self):
        self.calls = 0

    async def fetch(self, base: str, quote: str) -> Optional[Decimal]:
        self.calls += 1
        raise RuntimeError("the rate service returned something unparseable")


@dataclass
class StubSettings:
    """Only the fields :class:`HttpRateProvider` reads."""

    fx_enabled: bool = True
    fx_api_url: str = "https://rates.example.test/v6/latest"
    fx_api_key: str = ""
    fx_timeout_seconds: float = 5.0


@pytest.fixture
def http_settings(monkeypatch):
    """Point the HTTP provider at a URL `respx` can intercept.

    The real settings object is cached and shared, so it is replaced rather
    than mutated — a mutation would leak into every later test in the session.
    """
    stub = StubSettings()
    monkeypatch.setattr(fx_service, "get_settings", lambda: stub)
    return stub


async def _store(
    db,
    *,
    base: str = "GBP",
    quote: str = "CAD",
    rate: str = "1.70",
    on: Optional[date] = None,
    source: str = "service",
) -> FxRate:
    row = FxRate(
        base_currency=base,
        quote_currency=quote,
        rate_date=on or TODAY,
        rate=Decimal(rate),
        source=source,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# FR-028f: fetched once, reused for the day
# ---------------------------------------------------------------------------


class TestARateIsFetchedOncePerDay:
    """A marketplace day with forty sales is one request, not forty."""

    async def test_the_first_resolution_fetches_and_records(self, db_session) -> None:
        provider = CountingProvider("1.74")

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert resolved is not None
        assert resolved.rate == Decimal("1.74")
        assert resolved.as_of == TODAY
        assert resolved.source == "service"
        assert resolved.is_stale is False
        assert provider.call_count == 1

        stored = await latest_known_rate(db_session, "GBP", "CAD")
        assert stored is not None
        assert Decimal(str(stored.rate)) == Decimal("1.74")

    async def test_the_second_resolution_does_not_fetch_again(self, db_session) -> None:
        provider = CountingProvider("1.74")

        await resolve_rate(db_session, "GBP", "CAD", provider=provider)
        again = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert provider.call_count == 1, "the day's rate was already known"
        assert again is not None
        assert again.rate == Decimal("1.74")

    async def test_forty_sales_on_one_day_share_one_rate(self, db_session) -> None:
        """Both halves of FR-028f: one request, and one figure.

        Forty slightly different rates across one day's orders would make the
        day's margins disagree with each other for no reason a reader could
        see.
        """
        provider = CountingProvider("1.74")

        rates = {
            (await resolve_rate(db_session, "GBP", "CAD", provider=provider)).rate
            for _ in range(40)
        }

        assert provider.call_count == 1
        assert rates == {Decimal("1.74")}

    async def test_a_rate_already_recorded_is_reused_without_a_provider(
        self, db_session
    ) -> None:
        """Nothing is asked when the day's figure is already on record."""
        await _store(db_session, rate="1.68")
        provider = CountingProvider("9.99")

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert provider.call_count == 0
        assert resolved is not None
        assert resolved.rate == Decimal("1.68")
        assert "reused" in resolved.reason

    async def test_each_pair_is_counted_separately(self, db_session) -> None:
        provider = CountingProvider("1.74")

        await resolve_rate(db_session, "GBP", "CAD", provider=provider)
        await resolve_rate(db_session, "GBP", "USD", provider=provider)
        await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert provider.calls == [("GBP", "CAD"), ("GBP", "USD")]

    async def test_recording_the_same_day_twice_is_idempotent(self, db_session) -> None:
        """What makes day reuse safe when two sales race."""
        first = await record_rate(db_session, base="GBP", quote="CAD", rate=Decimal("1.74"))
        second = await record_rate(db_session, base="GBP", quote="CAD", rate=Decimal("1.74"))

        assert first.id == second.id

    async def test_currency_codes_are_normalised(self, db_session) -> None:
        """``gbp`` and ``GBP`` are the same pair, or reuse silently fails."""
        provider = CountingProvider("1.74")

        await resolve_rate(db_session, "gbp", "cad", provider=provider)
        await resolve_rate(db_session, " GBP ", "CAD", provider=provider)

        assert provider.call_count == 1

    async def test_the_same_currency_needs_no_rate_at_all(self, db_session) -> None:
        provider = CountingProvider("1.74")

        resolved = await resolve_rate(db_session, "GBP", "GBP", provider=provider)

        assert resolved is not None
        assert resolved.rate == Decimal("1")
        assert resolved.source == "parity"
        assert resolved.is_parity is True
        assert resolved.is_stale is False
        assert provider.call_count == 0, "no conversion applies, so nothing to fetch"
        assert await latest_known_rate(db_session, "GBP", "GBP") is None


# ---------------------------------------------------------------------------
# FR-028g: an unreachable service falls back, visibly
# ---------------------------------------------------------------------------


class TestAnUnreachableServiceFallsBack:
    """The last known rate is used, and it says which day it is from.

    A stale rate used silently is worse than one used visibly, because only
    the second can be questioned.
    """

    async def test_the_last_known_rate_is_used(self, db_session) -> None:
        await _store(db_session, rate="1.65", on=YESTERDAY)
        provider = CountingProvider(fails=True)

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert resolved is not None
        assert resolved.rate == Decimal("1.65")
        assert provider.call_count == 1, "it tried before falling back"

    async def test_the_fallback_carries_the_day_it_came_from(self, db_session) -> None:
        """FR-028g's actual requirement: the date travels with the figure."""
        await _store(db_session, rate="1.65", on=LAST_MONTH)
        provider = CountingProvider(fails=True)

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert resolved is not None
        assert resolved.as_of == LAST_MONTH
        assert resolved.is_stale is True
        assert str(LAST_MONTH) in resolved.reason

    async def test_a_current_rate_is_not_flagged_stale(self, db_session) -> None:
        await _store(db_session, rate="1.70", on=TODAY)

        resolved = await resolve_rate(db_session, "GBP", "CAD")

        assert resolved is not None
        assert resolved.is_stale is False

    async def test_the_most_recent_of_several_known_rates_wins(self, db_session) -> None:
        await _store(db_session, rate="1.50", on=LAST_MONTH)
        await _store(db_session, rate="1.65", on=YESTERDAY)
        provider = CountingProvider(fails=True)

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert resolved is not None
        assert resolved.rate == Decimal("1.65")
        assert resolved.as_of == YESTERDAY

    async def test_a_failed_fetch_records_nothing(self, db_session) -> None:
        """An outage must not leave a row that later reads as a real rate."""
        provider = CountingProvider(fails=True)

        await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert await latest_known_rate(db_session, "GBP", "CAD") is None

    @pytest.mark.parametrize("bad_rate", ["0", "-1.5"])
    async def test_a_nonsensical_fetched_rate_is_refused(
        self, db_session, bad_rate: str
    ) -> None:
        """A zero rate would value every foreign sale at nothing."""
        await _store(db_session, rate="1.65", on=YESTERDAY)
        provider = CountingProvider(bad_rate)

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert resolved is not None
        assert resolved.rate == Decimal("1.65"), "fell back rather than storing nonsense"
        assert resolved.is_stale is True


# ---------------------------------------------------------------------------
# FR-028h: a hand-entered rate overrides
# ---------------------------------------------------------------------------


class TestAManualRateOverrides:
    """An operator's figure wins, and what it replaced is still on record."""

    async def test_a_manual_rate_beats_a_fetched_one_for_the_same_day(
        self, db_session
    ) -> None:
        await _store(db_session, rate="1.70", on=TODAY, source="service")
        await set_manual_rate(
            db_session, base="GBP", quote="CAD", rate=Decimal("1.7250"), rate_date=TODAY
        )

        resolved = await resolve_rate(db_session, "GBP", "CAD")

        assert resolved is not None
        assert resolved.rate == Decimal("1.7250")
        assert resolved.source == "manual"
        assert "by hand" in resolved.reason

    async def test_the_override_does_not_destroy_the_fetched_figure(
        self, db_session
    ) -> None:
        """Kept as a separate row, so a reader can see what was overridden."""
        fetched = await _store(db_session, rate="1.70", on=TODAY, source="service")
        await set_manual_rate(
            db_session, base="GBP", quote="CAD", rate=Decimal("1.7250"), rate_date=TODAY
        )

        await db_session.refresh(fetched)
        assert Decimal(str(fetched.rate)) == Decimal("1.70")

    async def test_a_manual_rate_stops_the_day_being_fetched(self, db_session) -> None:
        await set_manual_rate(
            db_session, base="GBP", quote="CAD", rate=Decimal("1.7250"), rate_date=TODAY
        )
        provider = CountingProvider("1.70")

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert provider.call_count == 0
        assert resolved is not None
        assert resolved.rate == Decimal("1.7250")

    async def test_a_manual_rate_rescues_a_pair_with_no_service_coverage(
        self, db_session
    ) -> None:
        """The answer to the never-fetched pair: the operator supplies it."""
        provider = CountingProvider(None)
        assert await resolve_rate(db_session, "GBP", "XPF", provider=provider) is None

        await set_manual_rate(db_session, base="GBP", quote="XPF", rate=Decimal("135.5"))

        resolved = await resolve_rate(db_session, "GBP", "XPF", provider=provider)
        assert resolved is not None
        assert resolved.rate == Decimal("135.5")
        assert resolved.source == "manual"

    @pytest.mark.parametrize("bad_rate", ["0", "-2"])
    async def test_a_nonpositive_manual_rate_is_refused(self, db_session, bad_rate) -> None:
        with pytest.raises(ValueError):
            await set_manual_rate(
                db_session, base="GBP", quote="CAD", rate=Decimal(bad_rate)
            )

    async def test_a_manual_rate_is_only_preferred_on_its_own_day(
        self, db_session
    ) -> None:
        """Yesterday's override does not outrank today's fetched rate."""
        await set_manual_rate(
            db_session, base="GBP", quote="CAD", rate=Decimal("9.99"), rate_date=YESTERDAY
        )
        await _store(db_session, rate="1.70", on=TODAY, source="service")

        resolved = await resolve_rate(db_session, "GBP", "CAD")

        assert resolved is not None
        assert resolved.rate == Decimal("1.70")
        assert resolved.source == "service"


# ---------------------------------------------------------------------------
# FR-028i: a sale is never blocked
# ---------------------------------------------------------------------------


class TestASaleIsNeverBlocked:
    """``resolve_rate`` returns on every path a sale can reach.

    This is the clause that decides the module's shape. The sale path calls
    ``resolve_rate``; only the reporting path calls ``require_rate``.
    """

    async def test_an_outage_returns_rather_than_raises(self, db_session) -> None:
        await _store(db_session, rate="1.65", on=LAST_MONTH)

        resolved = await resolve_rate(
            db_session, "GBP", "CAD", provider=CountingProvider(fails=True)
        )

        assert resolved is not None

    async def test_a_pair_with_no_rate_returns_none_rather_than_raising(
        self, db_session
    ) -> None:
        assert (
            await resolve_rate(
                db_session, "GBP", "CAD", provider=CountingProvider(None)
            )
            is None
        )

    @pytest.mark.parametrize(
        "base,quote",
        [("", "CAD"), ("GBP", ""), ("", ""), (None, "CAD"), ("GBP", None)],
    )
    async def test_a_missing_currency_code_returns_none(
        self, db_session, base, quote
    ) -> None:
        """An order with no currency recorded must not raise at checkout."""
        assert await resolve_rate(db_session, base, quote) is None

    async def test_the_reporting_path_raises_where_the_sale_path_returns(
        self, db_session
    ) -> None:
        """The one deliberate difference between the two entry points."""
        provider = CountingProvider(None)

        assert await resolve_rate(db_session, "GBP", "CAD", provider=provider) is None

        with pytest.raises(RateUnavailableError):
            await require_rate(db_session, "GBP", "CAD", provider=provider)

    async def test_require_rate_succeeds_where_a_rate_exists(self, db_session) -> None:
        await _store(db_session, rate="1.70", on=TODAY)

        resolved = await require_rate(db_session, "GBP", "CAD")

        assert resolved.rate == Decimal("1.70")


# ---------------------------------------------------------------------------
# The defect this module is most likely to be "simplified" into
# ---------------------------------------------------------------------------


class TestAnUnknownRateIsNeverParity:
    """A never-fetched pair asks rather than implying 1:1.

    If somebody ever makes the unknown case return ``Decimal("1")``, every
    test above still passes and this one fails. That is its only job.
    """

    async def test_an_unknown_pair_is_none_not_one(self, db_session) -> None:
        resolved = await resolve_rate(
            db_session, "GBP", "CAD", provider=CountingProvider(None)
        )

        assert resolved is None, (
            "an unknown rate must read as unknown; returning 1.0 would price a "
            "cross-currency sale as though the two currencies were the same"
        )

    async def test_the_error_says_what_to_do_instead(self, db_session) -> None:
        with pytest.raises(RateUnavailableError) as caught:
            await require_rate(
                db_session, "GBP", "CAD", provider=CountingProvider(None)
            )

        message = str(caught.value)
        assert caught.value.base == "GBP"
        assert caught.value.quote == "CAD"
        assert "by hand" in message, "it must point at the override, FR-028h"
        assert "parity" in message

    async def test_parity_is_only_ever_returned_for_one_currency(
        self, db_session
    ) -> None:
        """The *only* route to a rate of 1 is the same code on both sides."""
        same = await resolve_rate(db_session, "CAD", "CAD")
        assert same is not None and same.rate == Decimal("1")

        different = await resolve_rate(
            db_session, "CAD", "GBP", provider=CountingProvider(None)
        )
        assert different is None


# ---------------------------------------------------------------------------
# FR-028j: a frozen rate is never revised
# ---------------------------------------------------------------------------


class TestAFrozenRateSurvivesABetterOne:
    """A rate on an order is a historical fact, not a cached lookup.

    Tested at the resolution layer — by asking for a past day after a newer,
    different rate has been recorded — because that is the read a margin
    report does when it revisits a settled order.
    """

    async def test_a_past_day_still_resolves_to_its_own_rate(self, db_session) -> None:
        await _store(db_session, rate="1.65", on=YESTERDAY)
        await _store(db_session, rate="1.82", on=TODAY)

        then = await resolve_rate(db_session, "GBP", "CAD", as_of=YESTERDAY)

        assert then is not None
        assert then.rate == Decimal("1.65")
        assert then.as_of == YESTERDAY

    async def test_a_backdated_resolution_never_fetches(self, db_session) -> None:
        """A provider cannot quote a past day, and asking would misdate it.

        Storing today's figure under yesterday's date is how a frozen rate
        would quietly become a revised one.
        """
        await _store(db_session, rate="1.65", on=YESTERDAY)
        provider = CountingProvider("9.99")

        resolved = await resolve_rate(
            db_session, "GBP", "CAD", as_of=YESTERDAY, provider=provider
        )

        assert provider.call_count == 0
        assert resolved is not None
        assert resolved.rate == Decimal("1.65")

    async def test_a_newly_recorded_rate_does_not_change_an_earlier_answer(
        self, db_session
    ) -> None:
        await _store(db_session, rate="1.65", on=YESTERDAY)
        before = await resolve_rate(db_session, "GBP", "CAD", as_of=YESTERDAY)

        await _store(db_session, rate="1.82", on=TODAY)
        after = await resolve_rate(db_session, "GBP", "CAD", as_of=YESTERDAY)

        assert before is not None and after is not None
        assert before.rate == after.rate == Decimal("1.65")

    async def test_a_manual_correction_today_does_not_restate_yesterday(
        self, db_session
    ) -> None:
        """An operator fixing today's rate must not move last month's margins."""
        await _store(db_session, rate="1.65", on=YESTERDAY)
        await set_manual_rate(
            db_session, base="GBP", quote="CAD", rate=Decimal("2.00"), rate_date=TODAY
        )

        then = await resolve_rate(db_session, "GBP", "CAD", as_of=YESTERDAY)

        assert then is not None
        assert then.rate == Decimal("1.65")

    async def test_a_rate_recorded_after_the_fact_is_not_used_for_an_earlier_day(
        self, db_session
    ) -> None:
        """A day with no rate stays unknown even once a later one is known."""
        await _store(db_session, rate="1.82", on=TODAY)

        assert (
            await resolve_rate(
                db_session,
                "GBP",
                "CAD",
                as_of=LAST_MONTH,
                provider=CountingProvider(None),
            )
            is None
        )


# ---------------------------------------------------------------------------
# Exactness, since a rate multiplies every converted figure
# ---------------------------------------------------------------------------


class TestRatesAreExact:
    """Constitution IV reaches the rate itself, not just the money.

    A rate is a multiplier on every converted figure, so a binary float here
    would put rounding error into money that was otherwise exact.
    """

    async def test_a_recorded_rate_round_trips_to_the_eighth_place(
        self, db_session
    ) -> None:
        await record_rate(
            db_session, base="GBP", quote="CAD", rate=Decimal("1.73456789")
        )

        resolved = await resolve_rate(db_session, "GBP", "CAD")

        assert resolved is not None
        assert resolved.rate == Decimal("1.73456789")

    async def test_the_resolved_rate_is_a_decimal(self, db_session) -> None:
        await _store(db_session, rate="1.70")

        resolved = await resolve_rate(db_session, "GBP", "CAD")

        assert resolved is not None
        assert isinstance(resolved.rate, Decimal)

    async def test_a_float_from_a_provider_does_not_stay_a_float(
        self, db_session
    ) -> None:
        """A provider sending a JSON number must not seed a binary float."""

        class FloatyProvider:
            async def fetch(self, base, quote):
                # Deliberately the value a JSON parser would hand over.
                return Decimal(str(0.1))

        resolved = await resolve_rate(
            db_session, "GBP", "CAD", provider=FloatyProvider()
        )

        assert resolved is not None
        assert isinstance(resolved.rate, Decimal)
        assert resolved.rate == Decimal("0.1")

    def test_a_resolved_rate_cannot_be_edited_after_the_fact(self) -> None:
        """``ResolvedRate`` is frozen, so nothing downstream can revise it."""
        resolved = fx_service.ResolvedRate(
            base_currency="GBP",
            quote_currency="CAD",
            rate=Decimal("1.70"),
            as_of=TODAY,
            source="service",
            is_stale=False,
            reason="fetched",
        )

        with pytest.raises(Exception):
            resolved.rate = Decimal("2.00")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# The one part that really speaks HTTP
# ---------------------------------------------------------------------------


class TestTheHttpProvider:
    """`respx` here, because this is the only piece with a network in it."""

    @respx.mock
    async def test_a_successful_fetch_returns_a_decimal(self, http_settings) -> None:
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"CAD": 1.7421}})
        )

        rate = await HttpRateProvider().fetch("GBP", "CAD")

        assert rate == Decimal("1.7421")
        assert isinstance(rate, Decimal)

    @respx.mock
    async def test_the_other_common_payload_shape_is_understood(
        self, http_settings
    ) -> None:
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"conversion_rates": {"CAD": 1.7421}})
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") == Decimal("1.7421")

    @respx.mock
    async def test_a_timeout_returns_none_rather_than_raising(
        self, http_settings
    ) -> None:
        """The protocol's contract, and the reason a sale survives an outage."""
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            side_effect=httpx.ConnectTimeout("too slow")
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") is None

    @respx.mock
    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_an_error_response_returns_none(self, http_settings, status) -> None:
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(status, json={})
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") is None

    @respx.mock
    async def test_a_response_missing_the_pair_returns_none(self, http_settings) -> None:
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"USD": 1.27}})
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") is None

    @respx.mock
    async def test_an_unusable_rate_returns_none(self, http_settings) -> None:
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"CAD": "not a number"}})
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") is None

    @respx.mock
    async def test_malformed_json_returns_none(self, http_settings) -> None:
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, content=b"<html>down for maintenance</html>")
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") is None

    @respx.mock
    async def test_fetching_can_be_switched_off_entirely(self, http_settings) -> None:
        """`fx_enabled = False` serves recorded rates only, with no requests."""
        http_settings.fx_enabled = False
        route = respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"CAD": 1.7421}})
        )

        assert await HttpRateProvider().fetch("GBP", "CAD") is None
        assert route.call_count == 0

    @respx.mock
    async def test_an_api_key_is_sent_as_a_header_not_a_query_parameter(
        self, http_settings
    ) -> None:
        """A key in a URL ends up in logs and proxies."""
        http_settings.fx_api_key = "secret-key"
        route = respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"CAD": 1.7421}})
        )

        await HttpRateProvider().fetch("GBP", "CAD")

        request = route.calls[0].request
        assert request.headers["apikey"] == "secret-key"
        assert "secret-key" not in str(request.url)

    @respx.mock
    async def test_the_pair_is_upper_cased_in_the_request(self, http_settings) -> None:
        route = respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"CAD": 1.7421}})
        )

        assert await HttpRateProvider().fetch("gbp", "cad") == Decimal("1.7421")
        assert route.call_count == 1

    @respx.mock
    async def test_the_http_provider_works_end_to_end_through_resolve_rate(
        self, db_session, http_settings
    ) -> None:
        """One test that is not holding the provider at arm's length."""
        respx.get("https://rates.example.test/v6/latest/GBP").mock(
            return_value=httpx.Response(200, json={"rates": {"CAD": 1.7421}})
        )

        resolved = await resolve_rate(
            db_session, "GBP", "CAD", provider=HttpRateProvider()
        )

        assert resolved is not None
        assert resolved.rate == Decimal("1.7421")
        assert resolved.source == "service"
        assert resolved.is_stale is False


class TestABadlyBehavedProviderIsNotHiddenFromTheDeveloper:
    """A provider that raises is a bug in the provider, and it surfaces.

    Swallowing every exception in ``resolve_rate`` would hide a broken adapter
    behind a permanently stale rate, which is harder to notice than a failure.
    The real provider does not raise — there are tests above for each way it
    could have — so this documents the boundary rather than asking for it to
    move.
    """

    async def test_an_exception_from_a_provider_propagates(self, db_session) -> None:
        provider = ExplodingProvider()

        with pytest.raises(RuntimeError):
            await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert provider.calls == 1

    async def test_a_known_rate_for_the_day_means_the_provider_is_never_reached(
        self, db_session
    ) -> None:
        """So a broken adapter cannot break a day whose rate is already known."""
        await _store(db_session, rate="1.70", on=TODAY)
        provider = ExplodingProvider()

        resolved = await resolve_rate(db_session, "GBP", "CAD", provider=provider)

        assert resolved is not None
        assert provider.calls == 0
