"""The packaging advisor: fit, ranking, filler, fragility and order packing (research D6, D7)."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.dims import Dims
from app.services.packaging_advisor import (
    ACCEPTED_DOES_NOT_FIT,
    DIMENSIONS_REQUIRED,
    NOTHING_FITS,
    Container,
    Filler,
    Wrap,
    accepted_packaging_warnings,
    suggest,
    suggest_for_order,
)

TEN = Decimal("10")


def d(length, width, height) -> Dims:
    return Dims(Decimal(str(length)), Decimal(str(width)), Decimal(str(height)))


def box(name, inner, *, in_stock=True, cost=None, kind="box") -> Container:
    return Container(
        id=uuid4(),
        name=name,
        kind=kind,
        inner=d(*inner) if inner is not None else None,
        in_stock=in_stock,
        unit_cost_key=Decimal(str(cost)) if cost is not None else None,
    )


def names(advice) -> list[str]:
    return [s.container.name for s in advice.suggestions]


STOCK = [box("S", (100, 100, 50)), box("M", (150, 100, 60)), box("L", (200, 150, 100))]


class TestSuggest:
    def test_spec_story_2_scenario_1(self) -> None:
        advice = suggest(d(120, 70, 30), STOCK, clearance=TEN)
        assert names(advice) == ["M", "L"]
        assert advice.warnings == ()

    def test_room_and_empty_volume(self) -> None:
        first = suggest(d(120, 70, 30), STOCK, clearance=TEN).suggestions[0]
        assert first.room == d(10, 10, 10)
        assert first.empty_volume_ml == Decimal("648")

    def test_a_container_without_inner_size_is_never_offered(self) -> None:
        """Spec 006 FR-006 (T021): an incomplete box or mailer is not suggested."""
        incomplete = [box("No size", None), box("No size mailer", None, kind="mailer")]
        advice = suggest(d(20, 20, 20), [*incomplete, box("S", (100, 100, 100))], clearance=TEN)
        assert names(advice) == ["S"]
        assert suggest(d(20, 20, 20), incomplete, clearance=TEN).suggestions == ()

    def test_rotated_fit_states_the_orientation(self) -> None:
        advice = suggest(d(30, 70, 120), [box("M", (150, 100, 60))], clearance=TEN)
        assert names(advice) == ["M"]
        assert advice.suggestions[0].orientation == ("height", "width", "length")

    def test_nothing_fits_gives_the_minimum_box(self) -> None:
        advice = suggest(d(300, 300, 300), STOCK, clearance=TEN)
        assert advice.suggestions == ()
        assert NOTHING_FITS in advice.warnings
        assert advice.minimum_inner == d(320, 320, 320)

    def test_minimum_box_is_sorted_longest_first(self) -> None:
        advice = suggest(d(30, 400, 70), STOCK, clearance=TEN)
        assert advice.minimum_inner == d(420, 90, 50)

    def test_incomplete_box_is_never_suggested_and_is_named(self) -> None:
        advice = suggest(d(10, 10, 10), [box("Half", None), *STOCK], clearance=TEN)
        assert "Half" not in names(advice)
        assert "incomplete_container:Half" in advice.warnings

    def test_out_of_stock_ranks_after_in_stock(self) -> None:
        stock = [box("Tiny-out", (60, 60, 60), in_stock=False), box("Big-in", (200, 200, 200))]
        assert names(suggest(d(10, 10, 10), stock, clearance=TEN)) == ["Big-in", "Tiny-out"]

    def test_equal_volume_ties_by_cost_then_unknown_cost_last_then_name(self) -> None:
        stock = [
            box("B-none", (100, 100, 100)),
            box("A-none", (100, 100, 100)),
            box("C-dear", (100, 100, 100), cost="0.90"),
            box("D-cheap", (100, 100, 100), cost="0.40"),
        ]
        assert names(suggest(d(10, 10, 10), stock, clearance=TEN)) == [
            "D-cheap",
            "C-dear",
            "A-none",
            "B-none",
        ]

    def test_mailer_is_checked_like_a_box(self) -> None:
        mailer = box("A4 mailer", (330, 240, 30), kind="mailer")
        assert names(suggest(d(200, 150, 10), [mailer], clearance=TEN)) == ["A4 mailer"]
        assert names(suggest(d(200, 150, 11), [mailer], clearance=TEN)) == []

    def test_zero_clearance_fits_an_exact_box(self) -> None:
        exact = box("Exact", (120, 70, 30))
        assert names(suggest(d(120, 70, 30), [exact], clearance=Decimal("0"))) == ["Exact"]
        assert names(suggest(d("120.1", 70, 30), [exact], clearance=Decimal("0"))) == []

    def test_exact_clearance_boundary(self) -> None:
        assert names(suggest(d(130, 80, 40), STOCK, clearance=TEN)) == ["M", "L"]
        assert names(suggest(d("130.1", 80, 40), STOCK, clearance=TEN)) == ["L"]

    def test_no_dimensions(self) -> None:
        advice = suggest(None, STOCK, clearance=TEN)
        assert advice.suggestions == ()
        assert advice.warnings[0] == DIMENSIONS_REQUIRED

    def test_never_a_false_fit(self) -> None:
        """SC-002 over a small grid: every suggestion fits in some orientation."""
        for length in (50, 95, 130, 131, 180):
            for width in (20, 60, 80, 81):
                for height in (10, 30, 40, 41, 90):
                    item = d(length, width, height)
                    for s in suggest(item, STOCK, clearance=TEN).suggestions:
                        assert s.container.inner is not None
                        assert item.plus(TEN).fits_in(s.container.inner) is not None


class TestFiller:
    def test_rounds_up_to_whole_units(self) -> None:
        # Spec Story 4 scenario 1: 1.6 l empty with 1 l per unit → 2 units.
        fill = Filler(uuid4(), "Paper", Decimal("1000"), True)
        container = box("Box", (200, 100, 100))  # 2000 ml
        item = d(100, 40, 100)  # 400 ml
        advice = suggest(item, [container], clearance=Decimal("0"), fillers=[fill])
        s = advice.suggestions[0]
        assert s.empty_volume_ml == Decimal("1600")
        assert s.void_fill is not None and s.void_fill.quantity == 2

    def test_picks_the_largest_stocked_filler(self) -> None:
        small = Filler(uuid4(), "Small", Decimal("200"), True)
        large = Filler(uuid4(), "Large", Decimal("1000"), True)
        larger_out = Filler(uuid4(), "Huge", Decimal("5000"), False)
        s = suggest(d(120, 70, 30), STOCK, clearance=TEN, fillers=[small, large, larger_out])
        void_fill = s.suggestions[0].void_fill
        assert void_fill is not None and void_fill.filler.name == "Large"
        assert void_fill.quantity == 1

    def test_no_filler_still_reports_empty_volume(self) -> None:
        s = suggest(d(120, 70, 30), STOCK, clearance=TEN).suggestions[0]
        assert s.void_fill is None
        assert s.empty_volume_ml == Decimal("648")

    def test_fragile_clearance_is_the_callers(self) -> None:
        # 120 × 70 × 30 with 20 mm needs 160 × 110 × 70: the 150 × 100 × 60 box goes.
        advice = suggest(d(120, 70, 30), STOCK, clearance=Decimal("20"), fragile=True)
        assert names(advice) == ["L"]
        assert advice.fragile

    def test_fragile_with_stocked_wrap(self) -> None:
        wrap = Wrap(uuid4(), "Bubble", True)
        s = suggest(d(10, 10, 10), STOCK, clearance=TEN, fragile=True, wraps=[wrap])
        assert s.suggestions[0].wrap == wrap

    def test_fragile_without_wrap_is_no_error(self) -> None:
        s = suggest(
            d(10, 10, 10), STOCK, clearance=TEN, fragile=True, wraps=[Wrap(uuid4(), "Out", False)]
        )
        assert s.suggestions[0].wrap is None

    def test_wrap_only_for_fragile(self) -> None:
        s = suggest(d(10, 10, 10), STOCK, clearance=TEN, wraps=[Wrap(uuid4(), "Bubble", True)])
        assert s.suggestions[0].wrap is None


class TestAcceptedPackagingWarning:
    def _consumable(self, inner):
        length, width, height = inner
        return SimpleNamespace(
            packaging_kind="box",
            inner_length_mm=length,
            inner_width_mm=width,
            inner_height_mm=height,
        )

    def test_flags_a_box_that_no_longer_fits(self) -> None:
        box_m = self._consumable((150, 100, 60))
        assert accepted_packaging_warnings(d(120, 70, 30), box_m, TEN) == []
        assert accepted_packaging_warnings(d(160, 100, 50), box_m, TEN) == [ACCEPTED_DOES_NOT_FIT]

    def test_silent_without_sizes(self) -> None:
        assert accepted_packaging_warnings(None, self._consumable((1, 1, 1)), TEN) == []
        assert accepted_packaging_warnings(d(1, 1, 1), None, TEN) == []
        assert (
            accepted_packaging_warnings(d(999, 1, 1), self._consumable((None, None, None)), TEN)
            == []
        )


class TestNoCostPath:
    def test_accepted_box_is_costed_by_costing_alone(self) -> None:
        """FR-021: the packaging line is `consumable_unit_cost × quantity`, from costing.py."""
        from app.services.costing import consumable_unit_cost
        from app.services.costing import _packaging_cost

        box_m = SimpleNamespace(
            id=uuid4(), current_cost_per_unit=Decimal("0.85"), purchases=[], packaging_kind="box"
        )
        product = SimpleNamespace(
            id=uuid4(), packaging_consumable=box_m, packaging_quantity=2, packaging_cost=0
        )
        cost, _origin = _packaging_cost(product, None)
        assert cost == consumable_unit_cost(box_m) * 2 == Decimal("1.70")

    def test_advice_carries_no_cost(self) -> None:
        advice = suggest(d(120, 70, 30), [box("M", (150, 100, 60), cost="0.85")], clearance=TEN)
        fields = vars(advice.suggestions[0])
        assert not any("cost" in name for name in fields)


class TestOrderPacking:
    def test_two_items_share_one_box(self) -> None:
        advice = suggest_for_order(
            [("A", d(100, 80, 40)), ("B", d(100, 80, 40))], STOCK, clearance=TEN
        )
        assert len(advice.parcels) == 1
        parcel = advice.parcels[0]
        assert parcel.container.name == "L"
        assert parcel.contents == {"A": 1, "B": 1}
        # The arrangement is stated: each unit's position and placed size.
        assert len(parcel.placements) == 2
        assert parcel.placements[0].position == (Decimal(0), Decimal(0), Decimal(0))

    def test_split_into_fewest_boxes_when_none_holds_all(self) -> None:
        # A and B each fill the largest box's footprint; C rides on top of A.
        advice = suggest_for_order(
            [("A", d(170, 120, 50)), ("B", d(170, 120, 50)), ("C", d(60, 60, 20))],
            STOCK,
            clearance=TEN,
        )
        assert len(advice.parcels) == 2
        contents = [p.contents for p in advice.parcels]
        assert contents == [{"A": 1, "C": 1}, {"B": 1}]

    def test_quantity_three_is_three_units(self) -> None:
        units = [("A", d(60, 60, 20))] * 3
        advice = suggest_for_order(units, STOCK, clearance=TEN)
        assert sum(p.contents.get("A", 0) for p in advice.parcels) == 3

    def test_clearance_is_around_the_group(self) -> None:
        # Two 65 × 80 × 40 side by side need 130 × 80 × 40 plus 20 per axis.
        exact = box("Exact", (150, 100, 60))
        advice = suggest_for_order(
            [("A", d(65, 80, 40)), ("B", d(65, 80, 40))], [exact], clearance=TEN
        )
        assert len(advice.parcels) == 1

    def test_nothing_can_hold_the_largest(self) -> None:
        advice = suggest_for_order([("Huge", d(500, 500, 500))], STOCK, clearance=TEN)
        assert advice.parcels == ()
        assert advice.warnings[0]["code"] == NOTHING_FITS

    def test_deterministic(self) -> None:
        units = [("A", d(90, 40, 30)), ("B", d(50, 50, 50)), ("C", d(30, 20, 10))] * 2
        first = suggest_for_order(units, STOCK, clearance=TEN)
        second = suggest_for_order(list(reversed(units)), STOCK, clearance=TEN)
        assert [p.contents for p in first.parcels] == [p.contents for p in second.parcels]
        assert [p.placements for p in first.parcels] == [p.placements for p in second.parcels]

    def test_placements_never_overlap_or_overflow(self) -> None:
        units = [("A", d(60, 40, 30))] * 6 + [("B", d(30, 30, 30))] * 4
        for parcel in suggest_for_order(units, STOCK, clearance=TEN).parcels:
            assert parcel.container.inner is not None
            space = parcel.container.inner.as_tuple()
            for p in parcel.placements:
                assert all(
                    p.position[i] + p.size.as_tuple()[i] <= space[i] - 2 * TEN for i in range(3)
                )
            for i, a in enumerate(parcel.placements):
                for b in parcel.placements[i + 1 :]:
                    assert not all(
                        a.position[k] < b.position[k] + b.size.as_tuple()[k]
                        and b.position[k] < a.position[k] + a.size.as_tuple()[k]
                        for k in range(3)
                    )
