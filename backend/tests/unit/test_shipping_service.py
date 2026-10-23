"""Unit tests for shipping service."""

from decimal import Decimal

import pytest

from app.services.channel_economics import ChannelEconomics
from app.services.shipping_service import ShippingService, get_shipping_service


class TestShippingService:
    """Tests for ShippingService."""

    @pytest.fixture
    def service(self):
        """A service carrying a £50 threshold, as a channel's economics would set it."""
        return ShippingService(free_shipping_threshold_pence=5000)

    def test_normalize_postcode_uppercase(self, service):
        """Test postcode normalization converts to uppercase."""
        assert service.normalize_postcode("sw1a 1aa") == "SW1A 1AA"
        assert service.normalize_postcode("SW1A 1AA") == "SW1A 1AA"

    def test_normalize_postcode_adds_space(self, service):
        """Test postcode normalization adds space."""
        assert service.normalize_postcode("SW1A1AA") == "SW1A 1AA"
        assert service.normalize_postcode("M11AE") == "M1 1AE"

    def test_normalize_postcode_removes_extra_spaces(self, service):
        """Test postcode normalization removes extra spaces."""
        assert service.normalize_postcode("SW1A  1AA") == "SW1A 1AA"
        assert service.normalize_postcode("  SW1A 1AA  ") == "SW1A 1AA"

    def test_validate_postcode_valid_formats(self, service):
        """Test validation of various valid UK postcode formats."""
        valid_postcodes = [
            "SW1A 1AA",  # AA9A 9AA
            "W1A 0AX",  # A9A 9AA
            "M1 1AE",  # A9 9AA
            "B33 8TH",  # A99 9AA
            "CR2 6XH",  # AA9 9AA
            "DN55 1PT",  # AA99 9AA
        ]
        for postcode in valid_postcodes:
            result = service.validate_postcode(postcode)
            assert result.valid is True, f"Expected {postcode} to be valid"

    def test_validate_postcode_invalid_formats(self, service):
        """Test validation rejects invalid postcodes."""
        invalid_postcodes = [
            "INVALID",
            "12345",
            "SW1",
            "1AA",
            "SW1A 1A",  # Too short
            "SW1A 1AAA",  # Too long
            "",
        ]
        for postcode in invalid_postcodes:
            result = service.validate_postcode(postcode)
            assert result.valid is False, f"Expected {postcode} to be invalid"

    def test_validate_postcode_identifies_highland_island(self, service):
        """Test validation correctly identifies Highland/Island areas."""
        highland_island_postcodes = [
            ("HS1 2AB", "Outer Hebrides"),
            ("IV1 1AA", "Scottish Highlands"),
            ("ZE1 0AA", "Shetland"),
            ("KW1 4AA", "Orkney"),
            ("BT1 1AA", "Northern Ireland"),
            ("JE1 1AA", "Channel Islands"),
            ("GY1 1AA", "Channel Islands"),
            ("IM1 1AA", "Isle of Man"),
        ]
        for postcode, expected_region in highland_island_postcodes:
            result = service.validate_postcode(postcode)
            assert result.valid is True
            assert result.is_highland_island is True, f"Expected {postcode} to be Highland/Island"
            assert result.region == expected_region

    def test_validate_postcode_mainland(self, service):
        """Test validation correctly identifies mainland UK areas."""
        mainland_postcodes = [
            ("SW1A 1AA", "London"),
            ("M1 1AE", "Greater Manchester"),
            ("B1 1AA", "West Midlands"),
            ("LS1 1AA", "West Yorkshire"),
            ("CF1 1AA", "South Wales"),
        ]
        for postcode, expected_region in mainland_postcodes:
            result = service.validate_postcode(postcode)
            assert result.valid is True
            assert result.is_highland_island is False, f"Expected {postcode} to be mainland"
            assert result.region == expected_region

    @pytest.mark.asyncio
    async def test_get_shipping_rates_valid_postcode(self, service):
        """Test getting rates for a valid postcode."""
        result = await service.get_shipping_rates("SW1A 1AA")

        assert result.postcode_valid is True
        assert len(result.options) == 4  # 4 standard options
        # The threshold it was given, not a constant of its own (T208).
        assert result.free_shipping_threshold_pence == 5000

    @pytest.mark.asyncio
    async def test_get_shipping_rates_invalid_postcode(self, service):
        """Test getting rates for an invalid postcode returns empty."""
        result = await service.get_shipping_rates("INVALID")

        assert result.postcode_valid is False
        assert len(result.options) == 0

    @pytest.mark.asyncio
    async def test_get_shipping_rates_highland_surcharge(self, service):
        """Test Highland/Island surcharge is applied."""
        mainland_result = await service.get_shipping_rates("SW1A 1AA")
        highland_result = await service.get_shipping_rates("IV1 1AA")

        # Find the same shipping method in both
        mainland_2nd = next(opt for opt in mainland_result.options if opt.id == "royal-mail-2nd")
        highland_2nd = next(opt for opt in highland_result.options if opt.id == "royal-mail-2nd")

        # Highland should be £3 (300 pence) more expensive
        assert highland_2nd.price_pence == mainland_2nd.price_pence + 300

    @pytest.mark.asyncio
    async def test_get_shipping_rates_free_shipping(self, service):
        """Test free shipping is applied when threshold met."""
        result = await service.get_shipping_rates(
            postcode="SW1A 1AA",
            cart_total_pence=5000,  # Exactly at threshold
        )

        assert result.qualifies_for_free_shipping is True

        # Basic shipping should be free
        free_option = next(opt for opt in result.options if opt.id == "royal-mail-2nd")
        assert free_option.price_pence == 0
        assert "FREE" in free_option.name

    @pytest.mark.asyncio
    async def test_get_shipping_rates_below_free_threshold(self, service):
        """Test no free shipping when below threshold."""
        result = await service.get_shipping_rates(
            postcode="SW1A 1AA",
            cart_total_pence=4999,  # Just below threshold
        )

        assert result.qualifies_for_free_shipping is False

        # Basic shipping should have normal price
        basic_option = next(opt for opt in result.options if opt.id == "royal-mail-2nd")
        assert basic_option.price_pence == 295

    def test_get_shipping_cost_known_method(self, service):
        """Test getting cost for a known shipping method."""
        name, cost = service.get_shipping_cost(
            shipping_method_id="royal-mail-2nd",
            postcode="SW1A 1AA",
        )

        assert name == "Royal Mail 2nd Class"
        assert cost == 295

    def test_get_shipping_cost_unknown_method(self, service):
        """Test getting cost for an unknown method returns default."""
        name, cost = service.get_shipping_cost(
            shipping_method_id="unknown-method",
            postcode="SW1A 1AA",
        )

        assert name == "Standard Shipping"
        assert cost == 395

    def test_get_shipping_cost_highland_surcharge(self, service):
        """Test Highland surcharge is applied to shipping cost."""
        name, mainland_cost = service.get_shipping_cost(
            shipping_method_id="royal-mail-2nd",
            postcode="SW1A 1AA",
        )
        name, highland_cost = service.get_shipping_cost(
            shipping_method_id="royal-mail-2nd",
            postcode="IV1 1AA",
        )

        assert highland_cost == mainland_cost + 300

    def test_get_shipping_cost_free_shipping(self, service):
        """Test free shipping when threshold met."""
        name, cost = service.get_shipping_cost(
            shipping_method_id="royal-mail-2nd",
            postcode="SW1A 1AA",
            cart_total_pence=5000,
        )

        assert cost == 0

    def test_get_shipping_cost_free_only_for_basic(self, service):
        """Test free shipping only applies to basic option."""
        # Basic shipping should be free
        _, basic_cost = service.get_shipping_cost(
            shipping_method_id="royal-mail-2nd",
            postcode="SW1A 1AA",
            cart_total_pence=5000,
        )
        assert basic_cost == 0

        # Express shipping should still have a cost
        _, express_cost = service.get_shipping_cost(
            shipping_method_id="royal-mail-tracked-24",
            postcode="SW1A 1AA",
            cart_total_pence=5000,
        )
        assert express_cost == 595  # Normal price


# ============================================
# The threshold is the channel's (T208)
# ============================================


class TestFreeShippingThresholdIsTheChannels:
    """The checkout applies the operator's threshold, never a constant."""

    def test_the_class_carries_no_threshold_of_its_own(self):
        assert not hasattr(ShippingService, "FREE_SHIPPING_THRESHOLD_PENCE")

    @pytest.mark.asyncio
    async def test_no_threshold_means_no_free_shipping(self):
        service = ShippingService()

        result = await service.get_shipping_rates("SW1A 1AA", cart_total_pence=1_000_000)

        assert result.free_shipping_threshold_pence is None
        assert result.qualifies_for_free_shipping is False
        second = next(opt for opt in result.options if opt.id == "royal-mail-2nd")
        assert second.price_pence == 295

    def test_no_threshold_charges_the_cost(self):
        _, cost = ShippingService().get_shipping_cost(
            "royal-mail-2nd", "SW1A 1AA", cart_total_pence=1_000_000
        )
        assert cost == 295

    def test_the_tenantless_dependency_offers_no_free_shipping(self):
        assert get_shipping_service().free_shipping_threshold_pence is None

    @pytest.mark.asyncio
    async def test_for_economics_applies_the_operators_threshold(self):
        service = ShippingService.for_economics(
            ChannelEconomics(free_shipping_threshold=Decimal("30.00"))
        )

        assert service.free_shipping_threshold_pence == 3000
        assert (
            await service.get_shipping_rates("SW1A 1AA", cart_total_pence=3000)
        ).qualifies_for_free_shipping
        assert not (
            await service.get_shipping_rates("SW1A 1AA", cart_total_pence=2999)
        ).qualifies_for_free_shipping

    def test_for_economics_converts_the_threshold_exactly(self):
        service = ShippingService.for_economics(
            ChannelEconomics(free_shipping_threshold=Decimal("79.99"))
        )
        # `int(79.99 * 100)` is 7998; the threshold must not lose the penny.
        assert service.free_shipping_threshold_pence == 7999

    def test_for_economics_without_a_threshold_offers_none(self):
        service = ShippingService.for_economics(ChannelEconomics())
        assert service.free_shipping_threshold_pence is None
