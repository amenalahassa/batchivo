"""Landed cost of filament: what a usable gram actually cost (FR-008).

A spool's purchase price is not what the filament cost. Inbound shipping
arrives once for a whole purchase and has to be spread across it; sales tax
belongs in the cost only when the operator cannot recover it; and the grams on
the core that no printer can reach were paid for but can never be sold.

Three rules, each from the spec:

* Shipping is allocated **by weight**, because weight is what drove the
  postage (FR-008b). Where a spool's weight is unknown the allocation falls
  back to an even split and says so (spec edge case), rather than refusing the
  purchase.
* Recoverable tax is excluded, non-recoverable tax included (FR-008c). Tax
  follows value rather than weight, so it is allocated by each spool's share of
  the purchase price -- falling back to the weight share when prices are
  missing.
* The per-gram figure divides by **usable** weight: nominal less the measured
  unusable remainder (FR-008d).

Every figure comes back with the trace that produced it (FR-008f), so a
per-gram cost can be explained without being recomputed by hand.

Constitution IV: exact decimal arithmetic throughout. No binary float appears
in this module, and ``tests/unit/pricing/test_no_float_in_money_paths.py``
fails the build if one ever does.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Sequence

from sqlalchemy import inspect as sa_inspect

if TYPE_CHECKING:
    from app.models.filament_purchase import FilamentPurchase
    from app.models.spool import Spool


ZERO = Decimal("0")


@dataclass(frozen=True)
class ShippingAllocation:
    """How a purchase's inbound shipping and tax were spread over its spools."""

    #: spool id -> allocated inbound shipping
    shipping_by_spool: dict[uuid.UUID, Decimal]
    #: spool id -> allocated non-recoverable tax (zero where tax is recoverable)
    tax_by_spool: dict[uuid.UUID, Decimal]
    #: True when weights were unusable and the split fell back to even shares.
    even_split_fallback: bool
    #: True when tax was spread by weight because prices were missing.
    tax_allocated_by_weight: bool
    #: Why a fallback was taken, in words, for the operator to read.
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class LandedCost:
    """One spool's landed cost, with the derivation FR-008f requires."""

    spool_id: Optional[uuid.UUID]
    purchase_price: Optional[Decimal]
    allocated_shipping: Decimal
    allocated_tax: Decimal
    tax_recoverable: bool
    nominal_weight_grams: Decimal
    unusable_remainder_grams: Decimal
    usable_weight_grams: Decimal
    total_landed_cost: Optional[Decimal]
    cost_per_gram: Optional[Decimal]
    even_split_fallback: bool = False
    incomplete_reasons: tuple[str, ...] = ()
    derivation: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_complete(self) -> bool:
        return self.cost_per_gram is not None and not self.incomplete_reasons


def _as_decimal(value: object) -> Optional[Decimal]:
    """Exact conversion through ``str``, so a JSON-sourced number stays exact."""
    if value is None:
        return None
    return Decimal(str(value))


def _relationship_loaded(instance: object, name: str) -> bool:
    """Whether ``name`` is already loaded on a mapped instance.

    The cost path is synchronous, so touching an unloaded relationship under
    asyncio raises rather than lazily loading. Asking first means a spool whose
    purchase was not eager-loaded falls back to its own price -- which is what
    FR-008e says a spool without a purchase does anyway -- instead of raising
    on a pricing screen.
    """
    try:
        state = sa_inspect(instance)
    except Exception:  # pragma: no cover - a plain object, as used in unit tests
        return hasattr(instance, name)
    if state is None:  # pragma: no cover - inspect raises rather than returning None
        return hasattr(instance, name)
    return name not in state.unloaded


def allocate_purchase(
    purchase: "FilamentPurchase",
    spools: Optional[Sequence["Spool"]] = None,
) -> ShippingAllocation:
    """Spread a purchase's shipping and tax across its spools.

    Shipping goes by weight (FR-008b). A spool whose nominal weight is missing
    or non-positive makes a weight split meaningless for the whole purchase, so
    the allocation falls back to an even split across every spool and records
    that it did -- the operator can then supply the weights and the figure
    improves, rather than the purchase being rejected.

    Adding a spool to a purchase re-runs this for every spool in it, which is
    why nothing is stored: the allocation is derived on read (Constitution V).
    A spool already consumed keeps the cost it was consumed at, which lives on
    the production run, not here.
    """
    members = list(spools if spools is not None else purchase.spools)
    shipping_total = _as_decimal(purchase.inbound_shipping_cost) or ZERO
    tax_total = _as_decimal(purchase.tax_amount) or ZERO
    recoverable = bool(purchase.tax_recoverable)
    notes: list[str] = []

    if not members:
        return ShippingAllocation(
            shipping_by_spool={},
            tax_by_spool={},
            even_split_fallback=False,
            tax_allocated_by_weight=False,
            notes=("the purchase has no spools, so there is nothing to allocate to",),
        )

    weights: dict[uuid.UUID, Decimal] = {}
    weights_usable = True
    for spool in members:
        weight = _as_decimal(spool.initial_weight)
        if weight is None or weight <= ZERO:
            weights_usable = False
            weight = ZERO
        weights[spool.id] = weight

    total_weight = sum(weights.values(), ZERO)
    if not weights_usable or total_weight <= ZERO:
        weights_usable = False
        notes.append(
            "at least one spool has no usable nominal weight, so shipping was "
            "split evenly rather than by weight"
        )

    count = Decimal(len(members))
    if weights_usable:
        shipping_by_spool = {
            spool_id: shipping_total * weight / total_weight for spool_id, weight in weights.items()
        }
    else:
        even = shipping_total / count
        shipping_by_spool = {spool.id: even for spool in members}

    if recoverable:
        tax_by_spool = {spool.id: ZERO for spool in members}
        tax_by_weight = False
        notes.append("recoverable sales tax was excluded from landed cost (FR-008c)")
    else:
        prices = {spool.id: _as_decimal(spool.purchase_price) for spool in members}
        total_price = sum((price for price in prices.values() if price is not None), ZERO)
        prices_usable = all(price is not None for price in prices.values()) and total_price > ZERO
        if prices_usable:
            tax_by_spool = {
                spool_id: tax_total * (price or ZERO) / total_price
                for spool_id, price in prices.items()
            }
            tax_by_weight = False
        elif weights_usable:
            tax_by_spool = {
                spool_id: tax_total * weight / total_weight for spool_id, weight in weights.items()
            }
            tax_by_weight = True
            notes.append("spool prices were missing, so non-recoverable tax was spread by weight")
        else:
            even_tax = tax_total / count
            tax_by_spool = {spool.id: even_tax for spool in members}
            tax_by_weight = False
            notes.append(
                "neither prices nor weights were usable, so non-recoverable tax was split evenly"
            )

    return ShippingAllocation(
        shipping_by_spool=shipping_by_spool,
        tax_by_spool=tax_by_spool,
        even_split_fallback=not weights_usable,
        tax_allocated_by_weight=tax_by_weight,
        notes=tuple(notes),
    )


def spool_landed_cost(
    spool: "Spool",
    purchase: Optional["FilamentPurchase"] = None,
    *,
    allocation: Optional[ShippingAllocation] = None,
) -> LandedCost:
    """What one usable gram of this spool cost, and how that was derived.

    ``purchase`` and ``allocation`` are optional: pass them when they are
    already loaded and the allocation is wanted. A spool with no purchase --
    every spool that existed before Tier 1 -- costs from its own price with no
    allocated shipping (FR-008e), which is exactly the figure it reported
    before this module existed.
    """
    price = _as_decimal(spool.purchase_price)
    nominal = _as_decimal(spool.initial_weight) or ZERO
    remainder = _as_decimal(spool.unusable_remainder_grams) or ZERO
    usable = nominal - remainder

    incomplete: list[str] = []
    derivation: list[str] = []

    if purchase is None and spool.filament_purchase_id is not None:
        if _relationship_loaded(spool, "filament_purchase"):
            purchase = spool.filament_purchase
        else:
            incomplete.append(
                "this spool belongs to a purchase that was not loaded, so its "
                "allocated shipping and tax are not included"
            )

    allocated_shipping = ZERO
    allocated_tax = ZERO
    recoverable = False
    even_split = False

    if purchase is not None:
        recoverable = bool(purchase.tax_recoverable)
        if allocation is None:
            allocation = allocate_purchase(purchase)
        allocated_shipping = allocation.shipping_by_spool.get(spool.id, ZERO)
        allocated_tax = allocation.tax_by_spool.get(spool.id, ZERO)
        even_split = allocation.even_split_fallback
        derivation.append(
            f"purchase {purchase.id}: shipping {purchase.inbound_shipping_cost} allocated "
            f"{'evenly' if even_split else 'by weight'} to {allocated_shipping}"
        )
        derivation.append(
            f"tax {purchase.tax_amount} "
            + (
                "excluded as recoverable"
                if recoverable
                else f"included as non-recoverable, allocated to {allocated_tax}"
            )
        )

    if price is None:
        incomplete.append("the spool has no purchase price, so no per-gram cost can be derived")
        total = None
    else:
        total = price + allocated_shipping + allocated_tax
        derivation.insert(0, f"purchase price {price}")

    if nominal <= ZERO:
        incomplete.append("the spool has no nominal weight, so no per-gram cost can be derived")
    elif usable <= ZERO:
        incomplete.append(
            "the unusable remainder is at least the whole spool, leaving no usable weight"
        )

    if usable > ZERO:
        derivation.append(
            f"usable weight {nominal} - {remainder} = {usable} g (FR-008d: never nominal)"
        )

    cost_per_gram = total / usable if (total is not None and usable > ZERO) else None
    if cost_per_gram is not None:
        derivation.append(f"landed {total} / {usable} g = {cost_per_gram} per gram")

    return LandedCost(
        spool_id=getattr(spool, "id", None),
        purchase_price=price,
        allocated_shipping=allocated_shipping,
        allocated_tax=allocated_tax,
        tax_recoverable=recoverable,
        nominal_weight_grams=nominal,
        unusable_remainder_grams=remainder,
        usable_weight_grams=usable if usable > ZERO else ZERO,
        total_landed_cost=total,
        cost_per_gram=cost_per_gram,
        even_split_fallback=even_split,
        incomplete_reasons=tuple(incomplete),
        derivation=tuple(derivation),
    )


def purchase_landed_costs(
    purchase: "FilamentPurchase",
    spools: Optional[Sequence["Spool"]] = None,
) -> dict[uuid.UUID, LandedCost]:
    """Landed cost for every spool on a purchase, from one allocation."""
    members = list(spools if spools is not None else purchase.spools)
    allocation = allocate_purchase(purchase, members)
    return {
        spool.id: spool_landed_cost(spool, purchase, allocation=allocation) for spool in members
    }
