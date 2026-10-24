"""Money crosses the wire as a decimal string, never as a JSON number.

Constitution IV requires exact decimal arithmetic end to end. The backend holds
`Decimal` and the database holds `Numeric`, but a JSON number undoes both: the
moment `20.30` is emitted unquoted, every consumer that parses it with a
standard JSON reader has a binary float, and the error is reintroduced at the
last place anyone thinks to look.

Pydantic v2 serialises `Decimal` to a string in JSON mode by default. That
default is a dependency's choice, not ours, and a single `ser_json_decimal`
setting or one `float` annotation would reverse it silently -- so it is pinned
here.

Scope: the cost and pricing schemas this feature owns, plus the console's order
read, which T201 brought in. The customer order schemas became `Decimal` with
T176 and the order responses with T201; payments still carry integer minor
units, which is a different representation rather than a lossy one.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.api.v1.orders import OrderItemResponse, OrderResponse
from app.schemas.model import CostBreakdown, CostLine, ModelCostBreakdown
from app.schemas.product import (
    ProductCostBreakdown,
    ProductPricingBase,
    ProductPricingCreate,
    ProductPricingResponse,
)

#: The schemas this feature is answerable for.
PRICING_SCHEMAS: list[type[BaseModel]] = [
    CostLine,
    CostBreakdown,
    ModelCostBreakdown,
    ProductCostBreakdown,
    ProductPricingBase,
    ProductPricingCreate,
    ProductPricingResponse,
    # The console's order read. `unit_price`, `total_price`, `shipping_cost`,
    # `subtotal` and `total` were `float` here until T201 -- the last money on
    # this API crossing the wire as JSON numbers -- and the float ban pinned
    # them by name rather than fixing them, because correcting them changes
    # the format `OrderDetail.tsx` and `OrderList.tsx` read (FR-047).
    OrderItemResponse,
    OrderResponse,
]


def _decimal_fields(schema: type[BaseModel]) -> list[str]:
    return [
        name for name, field in schema.model_fields.items() if "Decimal" in str(field.annotation)
    ]


def _a_cost_line() -> CostLine:
    return CostLine(
        key="material",
        label="Filament in the part",
        amount=Decimal("4.37"),
        risk_class="at_risk",
        source="observed",
        as_of=None,
    )


def _a_breakdown() -> CostBreakdown:
    return CostBreakdown(
        lines=[_a_cost_line()],
        at_risk_subtotal=Decimal("19.38"),
        not_at_risk_subtotal=Decimal("0.92"),
        yield_applied=Decimal("0.92"),
        failure_mode="per_part",
        failure_premium=Decimal("1.68"),
        total_make_cost=Decimal("20.30"),
        machine_hours=Decimal("9.5"),
        observed_share=Decimal("0.70"),
        assumed_share=Decimal("0.30"),
        incomplete_reasons=[],
    )


class TestTheDefaultHolds:
    """Pin the dependency behaviour everything below rests on."""

    def test_pydantic_renders_a_decimal_as_a_json_string(self) -> None:
        class Probe(BaseModel):
            amount: Decimal

        payload = json.loads(Probe(amount=Decimal("20.30")).model_dump_json())
        assert isinstance(payload["amount"], str), (
            "Pydantic is emitting Decimal as a JSON number. Something set "
            "ser_json_decimal to 'float'; every money field in the API is now "
            "lossy (Constitution IV)."
        )
        assert payload["amount"] == "20.30", "trailing zeros must survive the trip"

    def test_a_float_field_would_be_caught(self) -> None:
        """Prove the check below can fail, so a pass means something."""

        class Sloppy(BaseModel):
            amount: float

        payload = json.loads(Sloppy(amount=20.30).model_dump_json())
        assert isinstance(payload["amount"], (int, float))


class TestEveryMoneyFieldIsAString:
    def test_a_cost_line_amount_is_a_string(self) -> None:
        payload = json.loads(_a_cost_line().model_dump_json())
        assert payload["amount"] == "4.37"
        assert isinstance(payload["amount"], str)

    def test_every_decimal_on_a_breakdown_is_a_string(self) -> None:
        breakdown = _a_breakdown()
        payload = json.loads(breakdown.model_dump_json())
        for name in _decimal_fields(CostBreakdown):
            assert isinstance(payload[name], str), (
                f"CostBreakdown.{name} crossed the wire as {type(payload[name]).__name__}, "
                f"not a decimal string"
            )
        for line in payload["lines"]:
            assert isinstance(line["amount"], str)

    def test_an_unknown_figure_crosses_the_wire_as_null_not_zero(self) -> None:
        """FR-019: a gap is reported as a gap, through the serialiser too.

        ``machine_hours`` is null on an item nobody has timed. A zero would
        deserialise as a real figure -- an item that occupies no machine -- and
        a consumer dividing profit by it would then divide by zero instead of
        declining to report a rate.
        """
        breakdown = _a_breakdown().model_copy(update={"machine_hours": None})
        payload = json.loads(breakdown.model_dump_json())

        assert payload["machine_hours"] is None
        assert payload["machine_hours"] != 0

    def test_the_total_keeps_its_cents(self) -> None:
        payload = json.loads(_a_breakdown().model_dump_json())
        assert payload["total_make_cost"] == "20.30", (
            "the total lost its trailing zero, which means it went through a float"
        )

    @pytest.mark.parametrize("schema", PRICING_SCHEMAS, ids=[s.__name__ for s in PRICING_SCHEMAS])
    def test_no_pricing_schema_annotates_money_as_a_float(self, schema: type[BaseModel]) -> None:
        offenders = [
            name for name, field in schema.model_fields.items() if "float" in str(field.annotation)
        ]
        assert not offenders, (
            f"{schema.__name__} annotates {offenders} as float; money and rates "
            f"must be Decimal end to end (Constitution IV)"
        )

    @pytest.mark.parametrize("schema", PRICING_SCHEMAS, ids=[s.__name__ for s in PRICING_SCHEMAS])
    def test_every_pricing_schema_actually_carries_decimal_fields(
        self, schema: type[BaseModel]
    ) -> None:
        """A schema with no Decimal field would pass the scan vacuously."""
        assert _decimal_fields(schema), (
            f"{schema.__name__} has no Decimal field, so the float scan above "
            f"proves nothing about it -- either it lost its money fields or it "
            f"does not belong in PRICING_SCHEMAS"
        )


class TestMoneyIsAcceptedAsAString:
    """The input side matters as much: a client must be able to send a string."""

    def test_a_decimal_string_parses_without_passing_through_a_float(self) -> None:
        line = CostLine.model_validate(
            {
                "key": "machine",
                "label": "Machine time",
                "amount": "0.0000000000000001",
                "risk_class": "at_risk",
                "source": "measured",
                "as_of": None,
            }
        )
        assert line.amount == Decimal("0.0000000000000001"), (
            "a value too fine for a float survived, which means it was never one"
        )

    def test_a_price_accepts_a_decimal_string(self) -> None:
        from uuid import uuid4

        pricing = ProductPricingCreate.model_validate(
            {"sales_channel_id": str(uuid4()), "list_price": "64.99", "is_active": True}
        )
        assert pricing.list_price == Decimal("64.99")


class TestTheOrderReadCrossesTheWireExactly:
    """T201: the five figures every settled-order screen shows.

    Pinned by a rendered payload rather than only by annotation, because the
    annotation is half the claim -- a `ser_json_decimal` setting would turn all
    five back into JSON numbers without changing a single type hint.
    """

    @staticmethod
    def _an_order_item() -> OrderItemResponse:
        return OrderItemResponse(
            id=str(uuid4()),
            product_id=str(uuid4()),
            product_sku="THING-001",
            product_name="A printed thing",
            quantity=2,
            unit_price=Decimal("12.25"),
            total_price=Decimal("24.50"),
            fx_rate=Decimal("0.54321000"),
        )

    @classmethod
    def _an_order(cls) -> OrderResponse:
        now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        return OrderResponse(
            id=str(uuid4()),
            order_number="TEST-0001",
            status="pending",
            customer_email="buyer@example.invalid",
            customer_name="A Buyer",
            shipping_address_line1="1 Test Street",
            shipping_city="London",
            shipping_postcode="SW1A 1AA",
            shipping_country="United Kingdom",
            shipping_method="Standard",
            shipping_cost=Decimal("3.50"),
            postage_paid=Decimal("2.10"),
            sales_tax_collected=Decimal("4.67"),
            subtotal=Decimal("24.50"),
            total=Decimal("28.00"),
            currency="GBP",
            payment_provider="manual",
            payment_status="completed",
            created_at=now,
            updated_at=now,
            items=[cls._an_order_item()],
        )

    def test_every_money_field_on_an_order_is_a_decimal_string(self) -> None:
        payload = json.loads(self._an_order().model_dump_json())
        for name in _decimal_fields(OrderResponse):
            assert isinstance(payload[name], str), (
                f"OrderResponse.{name} crossed the wire as "
                f"{type(payload[name]).__name__}, not a decimal string"
            )

    def test_every_money_field_on_a_line_is_a_decimal_string(self) -> None:
        payload = json.loads(self._an_order().model_dump_json())
        line = payload["items"][0]
        for name in _decimal_fields(OrderItemResponse):
            assert isinstance(line[name], str), (
                f"OrderItemResponse.{name} crossed the wire as "
                f"{type(line[name]).__name__}, not a decimal string"
            )

    def test_the_figures_keep_their_trailing_zeros(self) -> None:
        """A lost trailing zero is the fingerprint of a float round trip."""
        payload = json.loads(self._an_order().model_dump_json())

        assert payload["subtotal"] == "24.50"
        assert payload["shipping_cost"] == "3.50"
        assert payload["total"] == "28.00"
        assert payload["items"][0]["total_price"] == "24.50"

    def test_the_figures_are_accepted_as_strings_on_the_way_in(self) -> None:
        """The order create form sends strings; nothing may coerce them early."""
        item = OrderItemResponse.model_validate(
            {
                "id": str(uuid4()),
                "product_id": None,
                "product_sku": "THING-001",
                "product_name": "A printed thing",
                "quantity": 1,
                "unit_price": "12.25",
                "total_price": "12.25",
            }
        )
        assert item.unit_price == Decimal("12.25")
