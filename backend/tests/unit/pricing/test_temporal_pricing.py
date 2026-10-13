"""Resolving a price as at a date, and refusing an incoherent history (T091).

FR-039: a product's price on a channel must be readable as at a date, so an
order reports the price effective when it was placed. The failure this prevents
is quiet and expensive — a margin report that values last quarter's orders at
this quarter's prices, which makes a price rise look like it was always there.

Three rules get the hardest tests here, because each has a boundary where an
off-by-one is invisible until it is wrong by a whole price:

1. **Overlapping date ranges are rejected at save time.** A read that found two
   applicable prices would have to pick one arbitrarily, so the write is
   refused instead (research D6).
2. **Overlapping quantity tiers are rejected.** Two tiers starting at the same
   quantity is a different mistake from two overlapping periods, and the
   service says which.
3. **The price at exactly a break quantity is unambiguous.** Tiers are
   half-open lower bounds and resolution takes the *highest* tier reached, so
   at 10 units a tier starting at 10 wins over one starting at 1.

The resolution functions are pure, so most of this file needs no database.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.product_pricing import ProductPricing
from app.services.temporal_pricing import (
    PriceOverlapError,
    assert_no_overlap,
    price_at,
    resolve_price,
    storefront_price,
)

PRODUCT = uuid4()
CHANNEL = uuid4()
OTHER_CHANNEL = uuid4()


def row(
    price: str,
    *,
    valid_from: date,
    valid_to: date | None = None,
    min_quantity: int = 1,
    channel=CHANNEL,
    is_active: bool = True,
) -> ProductPricing:
    """One unsaved price row.

    Transient rather than persisted: resolution is pure, and a test that needs
    a database to check an inequality is a test nobody runs.
    """
    return ProductPricing(
        id=uuid4(),
        product_id=PRODUCT,
        sales_channel_id=channel,
        list_price=Decimal(price),
        valid_from=valid_from,
        valid_to=valid_to,
        min_quantity=min_quantity,
        is_active=is_active,
    )


class FakeProduct:
    """A product with its pricing collections set explicitly.

    `current_pricing` is a filtered view of `pricing` in the real model; here
    the two are set independently so a test can check that the storefront reads
    the right one rather than happening to agree.
    """

    def __init__(self, pricing, current_pricing=None):
        self.pricing = list(pricing)
        self.current_pricing = (
            list(current_pricing)
            if current_pricing is not None
            else [p for p in pricing if p.valid_to is None]
        )


# ---------------------------------------------------------------------------
# FR-039: the price in effect on a date
# ---------------------------------------------------------------------------


class TestReadingThePriceThatApplied:
    """An order from an earlier period reports the price effective on its date."""

    @pytest.fixture
    def history(self) -> list[ProductPricing]:
        """Three periods, abutting without gaps or overlaps.

        CA$50 through June, CA$60 through July, CA$65 from August onwards —
        which is what `set_price` produces when a price is changed twice.
        """
        return [
            row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30)),
            row("60.00", valid_from=date(2026, 7, 1), valid_to=date(2026, 7, 31)),
            row("65.00", valid_from=date(2026, 8, 1)),
        ]

    @pytest.mark.parametrize(
        "on,expected",
        [
            (date(2026, 1, 1), "50.00"),
            (date(2026, 3, 15), "50.00"),
            (date(2026, 6, 30), "50.00"),
            (date(2026, 7, 1), "60.00"),
            (date(2026, 7, 31), "60.00"),
            (date(2026, 8, 1), "65.00"),
            (date(2027, 12, 25), "65.00"),
        ],
    )
    def test_each_date_resolves_to_the_price_that_applied(
        self, history, on: date, expected: str
    ) -> None:
        assert price_at(history, as_of=on) == Decimal(expected)

    def test_both_bounds_are_inclusive(self, history) -> None:
        """The last day of a period is still priced by it.

        This is the off-by-one that would otherwise lose a day: an order placed
        on 30 June must be charged June's price, not July's.
        """
        assert price_at(history, as_of=date(2026, 6, 30)) == Decimal("50.00")
        assert price_at(history, as_of=date(2026, 7, 1)) == Decimal("60.00")

    def test_a_one_day_period_prices_its_own_day(self) -> None:
        """A price set and replaced the same day still owned that day."""
        flash = [
            row("40.00", valid_from=date(2026, 5, 4), valid_to=date(2026, 5, 4)),
            row("65.00", valid_from=date(2026, 5, 5)),
        ]

        assert price_at(flash, as_of=date(2026, 5, 4)) == Decimal("40.00")
        assert price_at(flash, as_of=date(2026, 5, 5)) == Decimal("65.00")

    def test_a_date_before_the_first_period_is_unpriced(self, history) -> None:
        """``None``, not zero. A product nobody had listed was not free."""
        assert resolve_price(history, as_of=date(2025, 12, 31)) is None
        assert price_at(history, as_of=date(2025, 12, 31)) is None

    def test_a_gap_in_the_history_reads_as_unpriced(self) -> None:
        """A delisted period is not silently filled by a neighbour."""
        gapped = [
            row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 3, 31)),
            row("65.00", valid_from=date(2026, 6, 1)),
        ]

        assert resolve_price(gapped, as_of=date(2026, 4, 15)) is None

    def test_another_channel_is_not_consulted(self) -> None:
        """A price on one channel says nothing about another."""
        rows = [
            row("50.00", valid_from=date(2026, 1, 1), channel=CHANNEL),
            row("80.00", valid_from=date(2026, 1, 1), channel=OTHER_CHANNEL),
        ]

        assert price_at(rows, as_of=date(2026, 6, 1), sales_channel_id=CHANNEL) == Decimal("50.00")
        assert price_at(rows, as_of=date(2026, 6, 1), sales_channel_id=OTHER_CHANNEL) == Decimal(
            "80.00"
        )

    def test_an_empty_history_is_unpriced_rather_than_an_error(self) -> None:
        assert resolve_price([], as_of=date(2026, 6, 1)) is None


# ---------------------------------------------------------------------------
# Quantity tiers, and the boundary that matters
# ---------------------------------------------------------------------------


class TestQuantityTiers:
    """The price at exactly a break quantity must be unambiguous.

    Tiers are half-open lower bounds, resolved by taking the highest tier the
    quantity reaches. That single rule removes the ambiguity rather than
    leaving each caller to remember a convention.
    """

    @pytest.fixture
    def tiers(self) -> list[ProductPricing]:
        return [
            row("65.00", valid_from=date(2026, 1, 1), min_quantity=1),
            row("60.00", valid_from=date(2026, 1, 1), min_quantity=10),
            row("55.00", valid_from=date(2026, 1, 1), min_quantity=50),
        ]

    @pytest.mark.parametrize(
        "quantity,expected",
        [
            (1, "65.00"),
            (9, "65.00"),
            (10, "60.00"),
            (11, "60.00"),
            (49, "60.00"),
            (50, "55.00"),
            (5000, "55.00"),
        ],
    )
    def test_the_highest_tier_reached_wins(self, tiers, quantity, expected) -> None:
        assert price_at(tiers, as_of=date(2026, 6, 1), quantity=quantity) == Decimal(expected)

    def test_the_price_at_exactly_a_break_is_the_tier_that_starts_there(self, tiers) -> None:
        """Stated as its own test because it is the boundary the spec names.

        At exactly 10 units both the "1 or more" and the "10 or more" tier
        cover the quantity. The second wins, which is what a reader expects of
        a volume discount and what makes the figure predictable.
        """
        at_the_break = resolve_price(tiers, as_of=date(2026, 6, 1), quantity=10)

        assert at_the_break is not None
        assert at_the_break.min_quantity == 10
        assert Decimal(str(at_the_break.list_price)) == Decimal("60.00")

    def test_a_quantity_below_every_tier_is_unpriced(self) -> None:
        """A product priced only in tens has no price for one unit."""
        wholesale = [row("55.00", valid_from=date(2026, 1, 1), min_quantity=10)]

        assert resolve_price(wholesale, as_of=date(2026, 6, 1), quantity=1) is None

    def test_tiers_and_periods_resolve_together(self) -> None:
        """The tier in effect on the date, not the tier from another period."""
        rows = [
            row(
                "70.00",
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 6, 30),
                min_quantity=10,
            ),
            row("60.00", valid_from=date(2026, 7, 1), min_quantity=10),
            row("65.00", valid_from=date(2026, 1, 1), min_quantity=1),
        ]

        assert price_at(rows, as_of=date(2026, 3, 1), quantity=10) == Decimal("70.00")
        assert price_at(rows, as_of=date(2026, 9, 1), quantity=10) == Decimal("60.00")


# ---------------------------------------------------------------------------
# research D6: overlap is refused at save time
# ---------------------------------------------------------------------------


class TestOverlappingPeriodsAreRefused:
    """The invariant the database cannot express, kept here with a test.

    The partial unique index stops two *current* rows. Nothing in the schema
    stops two historical periods overlapping, and a read that found both would
    have to pick one arbitrarily — so the write is refused.
    """

    @pytest.fixture
    def existing(self) -> list[ProductPricing]:
        return [row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))]

    @pytest.mark.parametrize(
        "valid_from,valid_to",
        [
            # Starts inside, ends inside.
            (date(2026, 2, 1), date(2026, 3, 1)),
            # Starts before, ends inside.
            (date(2025, 1, 1), date(2026, 2, 1)),
            # Starts inside, ends after.
            (date(2026, 5, 1), date(2026, 12, 1)),
            # Encloses it entirely.
            (date(2025, 1, 1), date(2027, 1, 1)),
            # Identical.
            (date(2026, 1, 1), date(2026, 6, 30)),
            # Touching the last day.
            (date(2026, 6, 30), date(2026, 7, 30)),
            # Touching the first day.
            (date(2025, 12, 1), date(2026, 1, 1)),
            # Open-ended, starting inside.
            (date(2026, 3, 1), None),
            # Open-ended, starting before.
            (date(2025, 1, 1), None),
        ],
    )
    def test_every_kind_of_overlap_is_refused(self, existing, valid_from, valid_to) -> None:
        with pytest.raises(PriceOverlapError):
            assert_no_overlap(existing, valid_from=valid_from, valid_to=valid_to, min_quantity=1)

    @pytest.mark.parametrize(
        "valid_from,valid_to",
        [
            # Abutting after, by one day. This is what `set_price` produces.
            (date(2026, 7, 1), None),
            (date(2026, 7, 1), date(2026, 8, 1)),
            # Abutting before, by one day.
            (date(2025, 1, 1), date(2025, 12, 31)),
        ],
    )
    def test_an_abutting_period_is_allowed(self, existing, valid_from, valid_to) -> None:
        """Abutting is not overlapping, and it is the normal case.

        A price change closes one period the day before the next opens, so if
        this were refused no price could ever be changed.
        """
        assert_no_overlap(existing, valid_from=valid_from, valid_to=valid_to, min_quantity=1)

    def test_a_different_tier_does_not_collide(self, existing) -> None:
        """Tiers are independent periods: a "10 or more" price may coexist."""
        assert_no_overlap(
            existing,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 6, 30),
            min_quantity=10,
        )

    def test_a_row_being_edited_does_not_collide_with_itself(self, existing) -> None:
        assert_no_overlap(
            existing,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 6, 30),
            min_quantity=1,
            exclude_id=existing[0].id,
        )

    def test_the_refusal_names_the_row_it_collided_with(self, existing) -> None:
        """So the operator can see what they are about to contradict."""
        with pytest.raises(PriceOverlapError) as caught:
            assert_no_overlap(existing, valid_from=date(2026, 3, 1), valid_to=None, min_quantity=1)

        assert caught.value.existing is existing[0]
        assert "50.00" in str(caught.value)

    def test_an_open_ended_existing_period_blocks_anything_after_it(self) -> None:
        """A current price extends to infinity, so nothing may start inside it."""
        current = [row("65.00", valid_from=date(2026, 1, 1))]

        with pytest.raises(PriceOverlapError):
            assert_no_overlap(current, valid_from=date(2026, 8, 1), valid_to=None, min_quantity=1)


# ---------------------------------------------------------------------------
# The storefront read path
# ---------------------------------------------------------------------------


class TestTheStorefrontReadsOnlyCurrentPrices:
    """The blast radius research D6 flagged, tested at its narrowest point.

    Five shop read paths used to filter `product.pricing` in place. Since that
    collection became a history, every one of them would have served a
    superseded price. They all go through `storefront_price` now, so this is
    where that is checked.
    """

    def test_a_superseded_price_is_never_served(self) -> None:
        product = FakeProduct(
            [
                row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30)),
                row("65.00", valid_from=date(2026, 7, 1)),
            ]
        )

        assert storefront_price(product) == Decimal("65.00")

    def test_the_channels_own_price_is_preferred(self) -> None:
        product = FakeProduct(
            [
                row("65.00", valid_from=date(2026, 1, 1), channel=CHANNEL),
                row("80.00", valid_from=date(2026, 1, 1), channel=OTHER_CHANNEL),
            ]
        )

        assert storefront_price(product, sales_channel_id=CHANNEL) == Decimal("65.00")

    def test_it_falls_back_to_any_current_listing(self) -> None:
        """The behaviour the shop pages had, kept — but now temporal."""
        product = FakeProduct([row("80.00", valid_from=date(2026, 1, 1), channel=OTHER_CHANNEL)])

        assert storefront_price(product, sales_channel_id=CHANNEL) == Decimal("80.00")

    def test_an_inactive_listing_is_not_served(self) -> None:
        product = FakeProduct([row("65.00", valid_from=date(2026, 1, 1), is_active=False)])

        assert storefront_price(product) is None

    def test_an_unpriced_product_is_none_rather_than_zero(self) -> None:
        """The old code substituted zero, which put a free product on a page."""
        assert storefront_price(FakeProduct([])) is None

    def test_a_product_whose_only_price_has_expired_is_unpriced(self) -> None:
        product = FakeProduct(
            [row("65.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))]
        )

        assert storefront_price(product) is None

    def test_it_falls_back_to_filtering_history_when_the_view_is_absent(self) -> None:
        """A product loaded without `current_pricing` must not 500 a shop page.

        The relationship is eagerly loaded in production, but a caller
        constructing a Product by hand -- or a future change to the loading
        strategy -- should degrade to filtering rather than raise.
        """

        class WithoutTheView:
            def __init__(self, pricing):
                self.pricing = pricing
                self.current_pricing = None

        product = WithoutTheView(
            [
                row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30)),
                row("65.00", valid_from=date(2026, 7, 1)),
            ]
        )

        assert storefront_price(product) == Decimal("65.00")


class TestTheRowKnowsItsOwnPeriod:
    """`covers` and `is_current` on the model, since both read paths use them."""

    def test_a_current_row_says_so(self) -> None:
        assert row("65.00", valid_from=date(2026, 1, 1)).is_current is True

    def test_a_closed_row_says_so(self) -> None:
        closed = row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))
        assert closed.is_current is False

    def test_a_row_closed_in_the_future_is_not_current(self) -> None:
        """Read off ``valid_to``, not compared against today.

        The partial index guarantees one open row per tier; treating a
        future-dated close as "still current" would make two rows read as
        current and the invariant unprovable.
        """
        future = row("50.00", valid_from=date(2026, 1, 1), valid_to=date(2099, 1, 1))
        assert future.is_current is False

    def test_covers_respects_the_quantity_floor(self) -> None:
        tier = row("55.00", valid_from=date(2026, 1, 1), min_quantity=10)

        assert tier.covers(date(2026, 6, 1), quantity=10) is True
        assert tier.covers(date(2026, 6, 1), quantity=9) is False
