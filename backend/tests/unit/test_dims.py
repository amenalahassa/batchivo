"""The one fit check every packaging decision uses (research D6)."""

from decimal import Decimal
from types import SimpleNamespace

from app.services.dims import Dims


def d(length: str, width: str, height: str) -> Dims:
    return Dims(Decimal(length), Decimal(width), Decimal(height))


class TestFitsIn:
    def test_exact_fit_fits(self) -> None:
        assert d("120", "70", "30").fits_in(d("120", "70", "30")) == (
            "length",
            "width",
            "height",
        )

    def test_a_tenth_over_does_not_fit(self) -> None:
        assert d("120.1", "70", "30").fits_in(d("120", "70", "30")) is None

    def test_rotation_is_found_and_named(self) -> None:
        # 30 × 70 × 120 only fits a 120 × 70 × 30 box laid on its side.
        assert d("30", "70", "120").fits_in(d("120", "70", "30")) == (
            "height",
            "width",
            "length",
        )

    def test_unrotated_orientation_is_preferred(self) -> None:
        assert d("10", "10", "10").fits_in(d("50", "50", "50")) == (
            "length",
            "width",
            "height",
        )

    def test_no_orientation_fits(self) -> None:
        assert d("200", "10", "10").fits_in(d("150", "150", "150")) is None


class TestClearance:
    def test_plus_adds_twice_per_axis(self) -> None:
        assert d("120", "70", "30").plus(Decimal("10")) == d("140", "90", "50")

    def test_zero_clearance_is_the_item(self) -> None:
        item = d("120", "70", "30")
        assert item.plus(Decimal("0")) == item
        assert item.plus(Decimal("0")).fits_in(item) is not None


class TestValues:
    def test_volume_in_ml(self) -> None:
        assert d("150", "100", "60").volume_ml == Decimal("900")
        assert d("120", "70", "30").volume_ml == Decimal("252")

    def test_sorted_desc(self) -> None:
        assert d("30", "120", "70").sorted_desc() == d("120", "70", "30")

    def test_quantize_half_up(self) -> None:
        assert d("40.05", "29.94", "20").quantize() == d("40.1", "29.9", "20.0")

    def test_from_row_needs_all_three(self) -> None:
        assert Dims.from_row(SimpleNamespace(length_mm=1, width_mm=2, height_mm=None)) is None
        assert Dims.from_row(
            SimpleNamespace(inner_length_mm="1.5", inner_width_mm=2, inner_height_mm=3),
            prefix="inner_",
        ) == d("1.5", "2", "3")
