"""Item and parcel sizes as exact values (packaging advisor, research D6/D9).

``Dims`` is a box of length × width × height in millimetres, in ``Decimal``.
Every fit check in the feature -- box suggestions, the accepted-box warning,
carrier size classes, the printer-bed check -- goes through
:meth:`Dims.fits_in`, so "does it fit" has one answer.

``Parcel`` is what postage is decided from. It is a plain value kept here,
beside ``Dims``, so a model (``ShippingProfile.covers``) can take one without
importing the postage service; only ``postage.build_parcel`` assembles one.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import permutations
from typing import Any, Optional

AXES = ("length", "width", "height")
TENTH = Decimal("0.1")
ML_PER_MM3 = Decimal("1000")


@dataclass(frozen=True)
class Dims:
    """An axis-aligned box, in mm."""

    length: Decimal
    width: Decimal
    height: Decimal

    def as_tuple(self) -> tuple[Decimal, Decimal, Decimal]:
        return (self.length, self.width, self.height)

    def sorted_desc(self) -> "Dims":
        """The same box with its longest side first."""
        a, b, c = sorted(self.as_tuple(), reverse=True)
        return Dims(a, b, c)

    @property
    def volume_ml(self) -> Decimal:
        """Volume in millilitres (mm³ / 1000)."""
        return self.length * self.width * self.height / ML_PER_MM3

    def plus(self, clearance: Decimal) -> "Dims":
        """The box with ``clearance`` added on every side (2 × per axis)."""
        extra = Decimal(clearance) * 2
        return Dims(self.length + extra, self.width + extra, self.height + extra)

    def fits_in(self, other: "Dims") -> Optional[tuple[str, str, str]]:
        """The orientation this box fits ``other`` in, or ``None``.

        All six axis permutations are tried, the unrotated one first; equal
        sizes fit. The result names, for each of ``other``'s axes in turn
        (length, width, height), which of this box's axes lies along it.
        """
        mine = self.as_tuple()
        theirs = other.as_tuple()
        for order in permutations(range(3)):
            if all(mine[order[i]] <= theirs[i] for i in range(3)):
                return (AXES[order[0]], AXES[order[1]], AXES[order[2]])
        return None

    def quantize(self) -> "Dims":
        """Rounded to 0.1 mm, half up -- the precision dimensions are stored at."""
        return Dims(*(v.quantize(TENTH, rounding=ROUND_HALF_UP) for v in self.as_tuple()))

    @classmethod
    def from_row(cls, obj: Any, prefix: str = "") -> Optional["Dims"]:
        """Read ``<prefix>length_mm`` etc. from a row; ``None`` unless all three are set."""
        values = [getattr(obj, f"{prefix}{axis}_mm", None) for axis in AXES]
        if any(v is None for v in values):
            return None
        return cls(*(Decimal(str(v)) for v in values))


@dataclass(frozen=True)
class Parcel:
    """A parcel as postage sees it: packed weight and outer size, each possibly unknown.

    ``reasons`` says what is missing or assumed (an unknown weight, a wall
    taken as zero), so a screen can say why a postage is unknown or estimated.
    """

    grams: Optional[Decimal]
    outer: Optional[Dims]
    reasons: tuple[str, ...] = ()


__all__ = ["AXES", "Dims", "Parcel"]
