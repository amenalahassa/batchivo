"""The registry covers every numeric input the cost engine can reach.

research.md D1 accepted a known cost when it chose one side table over column
triples: **PostgreSQL cannot enforce a foreign key on a field name.** This file
is the enforcement that was promised in its place, and it is worth being blunt
about what that means -- if this test is deleted or weakened, nothing in the
system is guarding field names any more.

Coverage is derived rather than listed: the ORM models are walked for
cost-bearing numeric columns, and each must be registered or named in
:data:`NOT_A_COST_INPUT` with a reason. A new column on `models` or `printers`
therefore fails here until somebody decides which of the two it is, which is
the point -- a new input that silently has no provenance is a figure the
operator cannot weigh (FR-001).
"""

from decimal import Decimal

import pytest
from sqlalchemy import Integer, Numeric

from app.models.consumable import ConsumableType
from app.models.fee_rule import FeeRule
from app.models.filament_purchase import FilamentPurchase
from app.models.model import Model
from app.models.model_component import ModelComponent
from app.models.model_material import ModelMaterial
from app.models.model_printer_config import ModelPrinterConfig
from app.models.pricing_input_provenance import (
    PROVENANCE_ENTITY_TYPES,
    PROVENANCE_SOURCES,
)
from app.models.printer import Printer
from app.models.product import Product
from app.models.sales_channel import SalesChannel
from app.models.shipping_profile import ShippingProfile
from app.models.spool import Spool
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services.provenance import (
    REGISTERED_INPUTS,
    REGISTRY,
    FieldOrigin,
    UnknownProvenanceField,
    default_origin,
    known_entity_types,
    registered_fields,
    registry_entry,
)

#: entity_type -> the ORM class whose numeric columns must be accounted for.
COSTING_ENTITIES: dict[str, type] = {
    "model": Model,
    "model_material": ModelMaterial,
    "model_component": ModelComponent,
    "model_printer_config": ModelPrinterConfig,
    "product": Product,
    "printer": Printer,
    "spool": Spool,
    "filament_purchase": FilamentPurchase,
    "tenant_pricing_policy": TenantPricingPolicy,
    "sales_channel": SalesChannel,
    "fee_rule": FeeRule,
    "shipping_profile": ShippingProfile,
    "consumable_type": ConsumableType,
}
# `ProductPricing` is deliberately absent: a list price is the operator's
# decision that margins read, never an input to a cost (T249 checked it).

#: Numeric columns that are not inputs to a cost, each with the reason. A
#: column here is a deliberate exclusion; a column in neither place is a gap.
NOT_A_COST_INPUT: dict[str, dict[str, str]] = {
    "consumable_type": {
        "quantity_on_hand": "stock on hand, not a cost input",
        "reorder_point": "a restocking trigger, not money",
        "reorder_quantity": "a restocking quantity, not money",
        "typical_lead_days": "supplier lead time, not money",
    },
    "fee_rule": {
        "sort_order": "evaluation and presentation order, not money",
    },
    "model": {
        "units_in_stock": "inventory, not a cost input",
    },
    "model_printer_config": {
        "bed_temperature": "a slicer setting, not money or time",
        "nozzle_temperature": "a slicer setting, not money or time",
        "layer_height": "a slicer setting",
        "infill_percentage": "a slicer setting",
    },
    "product": {
        "units_in_stock": "inventory, not a cost input",
        "low_stock_threshold": "inventory policy, not a cost input",
        "weight_grams": "shipping weight of the finished item, used for postage not cost",
        "size_cm": "a dimension, not a cost input",
        "review_count": "a storefront figure",
        "average_rating": "a storefront figure",
        "print_time_hours": (
            "a storefront display estimate; the costed time is "
            "models.print_time_minutes and its per-printer override"
        ),
    },
    "printer": {
        "bed_size_x_mm": "a dimension",
        "bed_size_y_mm": "a dimension",
        "bed_size_z_mm": "a dimension",
        "nozzle_diameter_mm": "a hardware setting",
        "default_bed_temp": "a slicer setting",
        "default_nozzle_temp": "a slicer setting",
    },
    "spool": {
        "current_weight": "how much is left, not what it cost",
        "empty_spool_weight": "tare weight, used for gross-weight measurement",
    },
    "tenant_pricing_policy": {
        "sales_tax_recoverable": "a boolean policy flag, carried by the policy row itself",
    },
    # sales_channel has no exclusions: every numeric column it still carries is
    # a cost input and every one is registered. The blended `fee_percentage`
    # and `fee_fixed` were registered here too until task T123 dropped them;
    # a channel's fees are now its `fee_rules`.
}


def _numeric_columns(entity: type) -> set[str]:
    """Every integer or decimal column on a mapped class, ids excluded."""
    columns = entity.__table__.columns
    found: set[str] = set()
    for column in columns:
        if isinstance(column.type, (Numeric, Integer)) and not isinstance(column.type, type(None)):
            name = column.name
            if name.endswith("_id") or name == "id":
                continue
            found.add(name)
    return found


class TestEveryCostInputIsRegistered:
    """The coverage check research.md D1 promised in place of a constraint."""

    @pytest.mark.parametrize("entity_type", sorted(COSTING_ENTITIES))
    def test_no_numeric_column_is_unaccounted_for(self, entity_type: str) -> None:
        entity = COSTING_ENTITIES[entity_type]
        registered = registered_fields(entity_type)
        excluded = set(NOT_A_COST_INPUT.get(entity_type, {}))
        unaccounted = _numeric_columns(entity) - registered - excluded
        assert not unaccounted, (
            f"{entity_type} has numeric columns that are neither registered as "
            f"cost inputs nor excluded with a reason: {sorted(unaccounted)}. "
            f"Add each to REGISTRY in app/services/provenance.py, or to "
            f"NOT_A_COST_INPUT here saying why it is not a cost input."
        )

    @pytest.mark.parametrize("entity_type", sorted(COSTING_ENTITIES))
    def test_every_registered_field_exists_on_the_entity(self, entity_type: str) -> None:
        """A registry entry for a column nobody has is a name nothing validates."""
        entity = COSTING_ENTITIES[entity_type]
        columns = set(entity.__table__.columns.keys())
        missing = registered_fields(entity_type) - columns
        assert not missing, (
            f"the registry claims {entity_type} fields that do not exist: {sorted(missing)}"
        )

    @pytest.mark.parametrize("entity_type", sorted(COSTING_ENTITIES))
    def test_every_exclusion_names_a_real_column(self, entity_type: str) -> None:
        """A stale exclusion silently widens the gap it was meant to narrow."""
        entity = COSTING_ENTITIES[entity_type]
        columns = set(entity.__table__.columns.keys())
        stale = set(NOT_A_COST_INPUT.get(entity_type, {})) - columns
        assert not stale, f"{entity_type} exclusions name columns that are gone: {sorted(stale)}"

    def test_every_exclusion_carries_a_reason(self) -> None:
        for entity_type, exclusions in NOT_A_COST_INPUT.items():
            for name, reason in exclusions.items():
                assert reason and len(reason) > 10, (
                    f"{entity_type}.{name} is excluded without a usable reason"
                )


class TestTheRegistryAndTheDatabaseAgree:
    """The CHECK constraint and the Python registry must not drift apart."""

    def test_every_registered_entity_type_is_allowed_by_the_check(self) -> None:
        unknown = known_entity_types() - set(PROVENANCE_ENTITY_TYPES)
        assert not unknown, (
            f"the registry uses entity types the database CHECK rejects: {sorted(unknown)}"
        )

    def test_every_allowed_entity_type_is_used_by_the_registry(self) -> None:
        unused = set(PROVENANCE_ENTITY_TYPES) - known_entity_types()
        assert not unused, (
            f"the database allows entity types the registry knows nothing about: {sorted(unused)}"
        )

    def test_every_default_source_is_a_valid_source(self) -> None:
        for entry in REGISTERED_INPUTS:
            assert entry.default_source in PROVENANCE_SOURCES, (
                f"{entry.entity_type}.{entry.field_name} defaults to "
                f"{entry.default_source!r}, which the database rejects"
            )

    def test_the_entities_this_file_walks_match_the_allowed_types(self) -> None:
        """Otherwise an entity could be registered and never coverage-checked."""
        assert set(COSTING_ENTITIES) == set(PROVENANCE_ENTITY_TYPES)


class TestOperatorDecisionsAreMarkedAsSuch:
    """FR-002 and FR-042g: a decision is never moved by an automated process."""

    @pytest.mark.parametrize(
        ("entity_type", "field_name"),
        [
            ("tenant_pricing_policy", "print_labor_rate"),
            ("tenant_pricing_policy", "finishing_labor_rate"),
            ("tenant_pricing_policy", "default_target_margin_pct"),
            ("printer", "purchase_price"),
            ("printer", "expected_lifetime_hours"),
            ("model", "labor_rate_override"),
            ("model", "overhead_percentage"),
        ],
    )
    def test_the_decision_is_policy_by_default_and_not_learnable(
        self, entity_type: str, field_name: str
    ) -> None:
        entry = registry_entry(entity_type, field_name)
        assert entry.default_source == "policy"
        assert entry.learnable is False

    @pytest.mark.parametrize(
        ("entity_type", "field_name"),
        [
            ("model", "print_time_minutes"),
            ("model", "expected_yield"),
            ("model", "waste_grams"),
            ("model_material", "weight_grams"),
            ("printer", "measured_watts"),
        ],
    )
    def test_a_measurement_starts_assumed_and_can_be_learned(
        self, entity_type: str, field_name: str
    ) -> None:
        """FR-042a learns measurements; an unmeasured figure is an assumption."""
        entry = registry_entry(entity_type, field_name)
        assert entry.default_source == "assumed"
        assert entry.learnable is True


class TestLookingUpAnUnknownFieldIsRefused:
    def test_an_unregistered_field_raises(self) -> None:
        with pytest.raises(UnknownProvenanceField) as excinfo:
            registry_entry("model", "labor_hoursss")
        assert "labor_hoursss" in str(excinfo.value)
        assert "provenance.py" in str(excinfo.value)

    def test_an_unknown_entity_type_raises(self) -> None:
        with pytest.raises(UnknownProvenanceField):
            registry_entry("unicorn", "horn_length")

    def test_the_default_origin_comes_from_the_registry(self) -> None:
        origin = default_origin("printer", "purchase_price")
        assert origin.source == "policy"
        assert origin.is_default is True
        assert origin.as_of is None


class TestTheRegistryHasNoDuplicates:
    def test_each_key_appears_once(self) -> None:
        assert len(REGISTRY) == len(REGISTERED_INPUTS), (
            "two registry entries share an (entity_type, field_name) key, so one "
            "of them is unreachable"
        )

    def test_every_entry_carries_a_description(self) -> None:
        for entry in REGISTERED_INPUTS:
            assert entry.description, f"{entry.key} has no description"


class TestStalenessAndEvidence:
    """The two judgements a reader makes from an origin (FR-005, FR-046)."""

    def test_only_a_measured_figure_goes_stale(self) -> None:
        from datetime import date

        measured = FieldOrigin(source="measured", as_of=date(2025, 1, 1))
        policy = FieldOrigin(source="policy", as_of=date(2025, 1, 1))
        observed = FieldOrigin(source="observed", as_of=date(2025, 1, 1))
        today = date(2026, 10, 11)

        assert measured.is_stale(threshold_days=180, today=today) is True
        assert policy.is_stale(threshold_days=180, today=today) is False
        assert observed.is_stale(threshold_days=180, today=today) is False

    def test_a_fresh_measurement_is_not_stale(self) -> None:
        from datetime import date

        origin = FieldOrigin(source="measured", as_of=date(2026, 9, 1))
        assert origin.is_stale(threshold_days=180, today=date(2026, 10, 11)) is False

    def test_an_undated_figure_cannot_be_judged_stale(self) -> None:
        assert FieldOrigin(source="measured", as_of=None).is_stale(threshold_days=1) is False

    def test_an_assumption_is_not_evidence(self) -> None:
        assert FieldOrigin(source="assumed", as_of=None).is_evidenced is False
        assert FieldOrigin(source="measured", as_of=None).is_evidenced is True
        assert FieldOrigin(source="observed", as_of=None).is_evidenced is True
        assert FieldOrigin(source="policy", as_of=None).is_evidenced is True


class TestTheObservedShareOfABreakdown:
    """FR-046, computed from the lines so it answers 'trust *this* figure?'."""

    def _line(self, amount: str, source: str):
        from app.schemas.model import CostLine

        return CostLine(
            key="material",
            label="Filament",
            amount=Decimal(amount),
            risk_class="at_risk",
            source=source,
            as_of=None,
        )

    def test_the_shares_are_weighted_by_amount_not_by_count(self) -> None:
        from app.services.provenance import observed_share

        observed, assumed = observed_share(
            [self._line("9.00", "observed"), self._line("1.00", "assumed")]
        )
        assert observed == Decimal("0.9")
        assert assumed == Decimal("0.1")

    def test_the_shares_always_sum_to_one(self) -> None:
        from app.services.provenance import observed_share

        observed, assumed = observed_share(
            [
                self._line("4.51", "observed"),
                self._line("2.85", "policy"),
                self._line("6.25", "assumed"),
            ]
        )
        assert observed + assumed == Decimal("1")

    def test_a_zero_cost_breakdown_is_wholly_unevidenced(self) -> None:
        from app.services.provenance import observed_share

        assert observed_share([]) == (Decimal("0"), Decimal("1"))
