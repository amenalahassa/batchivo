"""Landed filament cost: shipping by weight, tax by recoverability, usable grams.

Four rules from the spec, each with its own failure mode if got wrong:

* **FR-008b** -- inbound shipping is allocated by weight. US2 scenario 5b has
  four equal spools landing at the golden CA$31.00 each; scenario 5c has a
  250 g spool carrying roughly a tenth of the shipping rather than a quarter.
* **FR-008c** -- recoverable tax is excluded, non-recoverable included.
* **FR-008d** -- the per-gram figure divides by usable weight.
* **Edge case** -- unknown weights fall back to an even split *and say so*,
  rather than refusing the purchase.

The CA$31.00 is not asserted as a constant: the purchase below is built so its
components sum to the fixture's own landed figure, and the expected per-spool
amount is derived from those components.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.filament_purchase import FilamentPurchase
from app.models.spool import Spool
from app.services.landed_cost import (
    allocate_purchase,
    purchase_landed_costs,
    spool_landed_cost,
)
from tests.fixtures import golden_case as golden

#: Split the golden landed cost into a price and a shipping share, so the test
#: can assert the sum reaches CA$31.00 from its parts rather than restating it.
SPOOLS_IN_PURCHASE = 4
SHIPPING_PER_SPOOL = Decimal("3.00")
SPOOL_PRICE = golden.SPOOL_LANDED_COST - SHIPPING_PER_SPOOL
TOTAL_SHIPPING = SHIPPING_PER_SPOOL * Decimal(SPOOLS_IN_PURCHASE)


def make_purchase(**overrides) -> FilamentPurchase:
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        supplier="Golden Filament Co",
        purchase_date=date(2026, 1, 15),
        inbound_shipping_cost=TOTAL_SHIPPING,
        tax_amount=Decimal("0"),
        tax_recoverable=False,
    )
    defaults.update(overrides)
    purchase = FilamentPurchase(**defaults)
    purchase.spools = []
    return purchase


def make_spool(
    weight: Decimal = golden.SPOOL_NOMINAL_GRAMS,
    price: Decimal = SPOOL_PRICE,
    remainder: Decimal | None = golden.SPOOL_UNUSABLE_REMAINDER_GRAMS,
    **overrides,
) -> Spool:
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        filament_type_id=uuid4(),
        spool_id=f"FIL-{uuid4().hex[:4]}",
        initial_weight=weight,
        current_weight=weight,
        purchase_price=price,
        unusable_remainder_grams=remainder,
        is_active=True,
        is_labeled=False,
    )
    defaults.update(overrides)
    return Spool(**defaults)


def attach(purchase: FilamentPurchase, *spools: Spool) -> FilamentPurchase:
    for spool in spools:
        spool.filament_purchase_id = purchase.id
        spool.filament_purchase = purchase
    purchase.spools = list(spools)
    return purchase


class TestFourEqualSpoolsSplitShippingEvenly:
    """US2 scenario 5b: equal weights, so an even split is what weight gives."""

    @pytest.fixture
    def purchase(self) -> FilamentPurchase:
        return attach(
            make_purchase(),
            *[make_spool() for _ in range(SPOOLS_IN_PURCHASE)],
        )

    def test_each_spool_carries_an_equal_share_of_the_shipping(self, purchase) -> None:
        allocation = allocate_purchase(purchase)
        shares = list(allocation.shipping_by_spool.values())
        assert all(share == SHIPPING_PER_SPOOL for share in shares), shares
        assert sum(shares, Decimal("0")) == TOTAL_SHIPPING

    def test_the_allocation_was_by_weight_not_a_fallback(self, purchase) -> None:
        """Equal shares here must come from equal weights, not from giving up."""
        assert allocate_purchase(purchase).even_split_fallback is False

    def test_each_spool_lands_at_the_golden_figure(self, purchase) -> None:
        for landed in purchase_landed_costs(purchase).values():
            assert landed.total_landed_cost == golden.SPOOL_LANDED_COST

    def test_the_per_gram_cost_divides_by_usable_weight(self, purchase) -> None:
        """FR-008d: nominal weight less the remainder, never the nominal weight."""
        usable = golden.SPOOL_NOMINAL_GRAMS - golden.SPOOL_UNUSABLE_REMAINDER_GRAMS
        expected = golden.SPOOL_LANDED_COST / usable
        for landed in purchase_landed_costs(purchase).values():
            assert landed.cost_per_gram == expected
            assert landed.usable_weight_grams == usable
            assert landed.cost_per_gram > golden.SPOOL_LANDED_COST / golden.SPOOL_NOMINAL_GRAMS

    def test_the_derivation_is_reported_so_the_figure_is_explainable(self, purchase) -> None:
        """FR-008f: price, allocated shipping, tax treatment, usable weight."""
        landed = next(iter(purchase_landed_costs(purchase).values()))
        trace = " | ".join(landed.derivation)
        assert str(SPOOL_PRICE) in trace
        assert "by weight" in trace
        assert "usable weight" in trace
        assert "per gram" in trace


class TestAMixedPurchaseAllocatesByWeight:
    """US2 scenario 5c: a 250 g spool among three 1 kg spools."""

    @pytest.fixture
    def purchase(self):
        small = make_spool(weight=Decimal("250"), price=Decimal("9.00"))
        large = [make_spool(weight=Decimal("1000"), price=Decimal("28.00")) for _ in range(3)]
        return attach(make_purchase(), small, *large), small, large

    def test_the_small_spool_carries_its_weight_share_not_a_quarter(self, purchase) -> None:
        bundle, small, large = purchase
        allocation = allocate_purchase(bundle)
        total_weight = Decimal("250") + Decimal("3000")
        expected = TOTAL_SHIPPING * Decimal("250") / total_weight
        assert allocation.shipping_by_spool[small.id] == expected

        even_share = TOTAL_SHIPPING / Decimal("4")
        assert allocation.shipping_by_spool[small.id] < even_share / Decimal("2"), (
            "the light spool was charged near a quarter of the shipping, so the "
            "allocation is not by weight (FR-008b)"
        )

    def test_roughly_a_tenth_of_the_shipping_as_the_spec_states_it(self, purchase) -> None:
        bundle, small, _large = purchase
        share = allocate_purchase(bundle).shipping_by_spool[small.id] / TOTAL_SHIPPING
        assert Decimal("0.06") < share < Decimal("0.09"), (
            f"the 250 g spool carried {share} of the shipping, not roughly a tenth"
        )

    def test_the_whole_shipping_charge_is_allocated_and_none_invented(self, purchase) -> None:
        bundle, _small, _large = purchase
        allocated = sum(allocate_purchase(bundle).shipping_by_spool.values(), Decimal("0"))
        assert allocated == TOTAL_SHIPPING

    def test_the_heavy_spools_share_the_rest_equally(self, purchase) -> None:
        bundle, _small, large = purchase
        allocation = allocate_purchase(bundle)
        shares = {allocation.shipping_by_spool[spool.id] for spool in large}
        assert len(shares) == 1, "equal weights were allocated unequal shipping"


class TestTaxFollowsRecoverability:
    """FR-008c and US2 scenario 5d: the same purchase, two tax registrations."""

    TAX = Decimal("5.20")

    def _landed(self, recoverable: bool):
        purchase = attach(
            make_purchase(tax_amount=self.TAX, tax_recoverable=recoverable),
            *[make_spool() for _ in range(SPOOLS_IN_PURCHASE)],
        )
        return purchase_landed_costs(purchase)

    def test_recoverable_tax_is_excluded_from_cost(self) -> None:
        for landed in self._landed(True).values():
            assert landed.allocated_tax == Decimal("0")
            assert landed.total_landed_cost == golden.SPOOL_LANDED_COST

    def test_non_recoverable_tax_is_included_in_cost(self) -> None:
        expected_share = self.TAX / Decimal(SPOOLS_IN_PURCHASE)
        for landed in self._landed(False).values():
            assert landed.allocated_tax == expected_share
            assert landed.total_landed_cost == golden.SPOOL_LANDED_COST + expected_share

    def test_the_two_registrations_differ_by_exactly_the_tax(self) -> None:
        recoverable = sum(
            (landed.total_landed_cost for landed in self._landed(True).values()), Decimal("0")
        )
        not_recoverable = sum(
            (landed.total_landed_cost for landed in self._landed(False).values()), Decimal("0")
        )
        assert not_recoverable - recoverable == self.TAX

    def test_the_exclusion_is_stated_rather_than_silent(self) -> None:
        purchase = attach(make_purchase(tax_amount=self.TAX, tax_recoverable=True), make_spool())
        notes = " | ".join(allocate_purchase(purchase).notes)
        assert "recoverable" in notes

    def test_non_recoverable_tax_follows_value_when_prices_differ(self) -> None:
        """Tax is charged on price, so it is allocated on price, not weight."""
        cheap = make_spool(weight=Decimal("1000"), price=Decimal("10.00"))
        dear = make_spool(weight=Decimal("1000"), price=Decimal("30.00"))
        purchase = attach(
            make_purchase(tax_amount=Decimal("4.00"), tax_recoverable=False), cheap, dear
        )
        allocation = allocate_purchase(purchase)
        assert allocation.tax_by_spool[dear.id] == Decimal("3.00")
        assert allocation.tax_by_spool[cheap.id] == Decimal("1.00")


class TestUnknownWeightsFallBackAndSaySo:
    """Spec edge case: shipping cannot be allocated by weight, so it is not."""

    @pytest.fixture
    def purchase(self):
        known = make_spool(weight=Decimal("1000"))
        unknown = make_spool(weight=Decimal("0"))
        return attach(make_purchase(), known, unknown), known, unknown

    def test_the_split_is_even(self, purchase) -> None:
        bundle, known, unknown = purchase
        allocation = allocate_purchase(bundle)
        half = TOTAL_SHIPPING / Decimal("2")
        assert allocation.shipping_by_spool[known.id] == half
        assert allocation.shipping_by_spool[unknown.id] == half

    def test_the_fallback_is_flagged(self, purchase) -> None:
        bundle, _known, _unknown = purchase
        allocation = allocate_purchase(bundle)
        assert allocation.even_split_fallback is True

    def test_the_fallback_is_explained_in_words(self, purchase) -> None:
        bundle, _known, _unknown = purchase
        notes = " | ".join(allocate_purchase(bundle).notes)
        assert "evenly" in notes and "weight" in notes

    def test_the_flag_reaches_each_spools_landed_cost(self, purchase) -> None:
        bundle, known, _unknown = purchase
        assert purchase_landed_costs(bundle)[known.id].even_split_fallback is True

    def test_the_purchase_is_not_refused(self, purchase) -> None:
        bundle, known, _unknown = purchase
        landed = purchase_landed_costs(bundle)[known.id]
        assert landed.cost_per_gram is not None


class TestASpoolWithoutAPurchaseStillWorks:
    """FR-008e: every spool that existed before Tier 1."""

    def test_it_costs_from_its_own_price_with_no_allocated_shipping(self) -> None:
        spool = make_spool(remainder=None)
        landed = spool_landed_cost(spool)
        assert landed.allocated_shipping == Decimal("0")
        assert landed.allocated_tax == Decimal("0")
        assert landed.cost_per_gram == SPOOL_PRICE / golden.SPOOL_NOMINAL_GRAMS

    def test_the_figure_is_what_it_was_before_landed_cost_existed(self) -> None:
        """The pre-Tier 1 property divided price by initial weight; so must this."""
        spool = make_spool(remainder=None)
        assert spool.cost_per_gram == SPOOL_PRICE / golden.SPOOL_NOMINAL_GRAMS

    def test_a_recorded_remainder_still_narrows_the_divisor(self) -> None:
        spool = make_spool(remainder=Decimal("25"))
        assert spool.cost_per_gram == SPOOL_PRICE / Decimal("975")

    def test_nothing_is_reported_as_missing(self) -> None:
        assert spool_landed_cost(make_spool(remainder=None)).incomplete_reasons == ()


class TestWhatCannotBeDerivedIsReported:
    """A per-gram cost that cannot be derived is said to be missing, not zeroed."""

    def test_no_purchase_price_is_reported(self) -> None:
        landed = spool_landed_cost(make_spool(price=None))
        assert landed.cost_per_gram is None
        assert any("purchase price" in reason for reason in landed.incomplete_reasons)

    def test_no_nominal_weight_is_reported(self) -> None:
        landed = spool_landed_cost(make_spool(weight=Decimal("0"), remainder=None))
        assert landed.cost_per_gram is None
        assert any("nominal weight" in reason for reason in landed.incomplete_reasons)

    def test_a_remainder_swallowing_the_spool_is_reported(self) -> None:
        landed = spool_landed_cost(make_spool(weight=Decimal("1000"), remainder=Decimal("1000")))
        assert landed.cost_per_gram is None
        assert any("usable weight" in reason for reason in landed.incomplete_reasons)

    def test_an_empty_purchase_allocates_nothing_and_says_why(self) -> None:
        allocation = allocate_purchase(make_purchase())
        assert allocation.shipping_by_spool == {}
        assert any("no spools" in note for note in allocation.notes)


class TestAddingASpoolRecomputesTheWholeAllocation:
    """Spec edge case: a spool added after shipping was already allocated."""

    def test_every_spools_share_falls_when_another_joins(self) -> None:
        purchase = make_purchase()
        first = make_spool()
        attach(purchase, first)
        before = allocate_purchase(purchase).shipping_by_spool[first.id]

        second = make_spool()
        attach(purchase, first, second)
        after = allocate_purchase(purchase).shipping_by_spool[first.id]

        assert before == TOTAL_SHIPPING
        assert after == TOTAL_SHIPPING / Decimal("2")
        assert after < before

    def test_nothing_is_stored_so_there_is_nothing_to_invalidate(self) -> None:
        """Constitution V: the allocation is derived on read, never persisted."""
        purchase = make_purchase()
        spool = make_spool()
        attach(purchase, spool)
        assert not hasattr(spool, "allocated_shipping_cost")
        assert not hasattr(spool, "landed_cost_per_gram_stored")
