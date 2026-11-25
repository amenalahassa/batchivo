"""The shipped catalogue and tariff files, and the loader that validates them (T003)."""

import copy
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import catalogue_data as cd

# ============================================
# Helpers
# ============================================


def _box(**overrides) -> dict:
    item = {
        "key": "box-test",
        "name": "Test box",
        "kind": "box",
        "inner_length_mm": "100",
        "inner_width_mm": "80",
        "inner_height_mm": "60",
        "wall_mm": "3",
        "empty_weight_grams": "40",
        "typical_cost": {"CAD": "1.00"},
        "source": "test",
    }
    item.update(overrides)
    return item


def _catalogue(*items: dict) -> dict:
    return {"version": 1, "as_of": "2026-11-01", "items": list(items)}


def _tariff(**overrides) -> dict:
    tariff = {
        "carrier": "canada_post",
        "name": "Canada Post",
        "currency": "CAD",
        "effective_date": "2026-01-12",
        "source": "test",
        "services": [
            {
                "key": "small_packet",
                "name": "Small Packet",
                "max_length_mm": "600",
                "max_width_mm": "400",
                "max_height_mm": "400",
                "zones": [
                    {
                        "zone": "us",
                        "brackets": [
                            {"min_grams": "0", "max_grams": "100", "price": "9.11"},
                            {"min_grams": "100", "max_grams": None, "price": "11.13"},
                        ],
                    }
                ],
            }
        ],
    }
    tariff.update(overrides)
    return tariff


def _write_tariff(root: Path, data: dict, name: str | None = None) -> Path:
    folder = root / data["carrier"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name or data['effective_date']}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _fresh_caches():
    cd.clear_caches()
    yield
    cd.clear_caches()


# ============================================
# Shipped files
# ============================================


class TestShippedFiles:
    def test_packaging_catalogue_loads(self):
        catalogue = cd.load_packaging_catalogue()
        assert catalogue.version >= 1
        assert len(catalogue.items) == len(catalogue.by_key())

    def test_packaging_catalogue_meets_fr009_minimums(self):
        kinds = Counter(item.kind for item in cd.load_packaging_catalogue().items)
        assert kinds["box"] >= 8
        assert kinds["mailer"] >= 3
        assert kinds["void_fill"] + kinds["wrap"] >= 3

    def test_every_item_has_a_typical_cost_in_every_catalogue_currency(self):
        for item in cd.load_packaging_catalogue().items:
            assert set(item.typical_cost) == set(cd.CATALOGUE_CURRENCIES), item.key

    def test_boxes_cover_cube_and_flat_shapes(self):
        boxes = [i for i in cd.load_packaging_catalogue().items if i.kind == "box"]
        cubes = [b for b in boxes if b.inner_length_mm == b.inner_width_mm == b.inner_height_mm]
        flats = [b for b in boxes if b.inner_height_mm < b.inner_width_mm]
        assert cubes and flats

    def test_every_tariff_file_loads(self):
        tariffs = cd.load_tariffs()
        assert {t.carrier for t in tariffs} == set(cd.CARRIER_CURRENCY)

    def test_each_carrier_ships_its_fr016_services(self):
        for carrier, services in cd.CARRIER_SERVICES.items():
            latest = cd.latest_tariff(carrier)
            assert latest is not None
            assert {s.key for s in latest.services} == set(services), carrier

    def test_every_carrier_prices_a_domestic_zone(self):
        for carrier in cd.CARRIER_CURRENCY:
            zones = {z.zone for s in cd.latest_tariff(carrier).services for z in s.zones}
            assert "domestic" in zones, carrier

    def test_prices_are_decimals_not_floats(self):
        bracket = cd.latest_tariff("usps").services[0].zones[0].brackets[0]
        assert isinstance(bracket.price, Decimal)

    def test_tariff_lookup_by_date(self):
        latest = cd.latest_tariff("la_poste")
        assert cd.tariff("la_poste", latest.effective_date) is latest
        assert cd.latest_tariff("nobody") is None


# ============================================
# Packaging catalogue validation
# ============================================


class TestPackagingValidation:
    def test_a_valid_catalogue_loads(self, tmp_path, monkeypatch):
        path = tmp_path / "packaging.json"
        path.write_text(json.dumps(_catalogue(_box())), encoding="utf-8")
        monkeypatch.setattr(cd, "PACKAGING_CATALOGUE_PATH", path)
        assert cd.load_packaging_catalogue().items[0].inner_length_mm == Decimal("100")

    @pytest.mark.parametrize(
        "items",
        [
            pytest.param([_box(), _box(name="Other")], id="duplicate-key"),
            pytest.param([_box(), _box(key="box-two")], id="duplicate-name-in-kind"),
            pytest.param([_box(wall_mm=None)], id="box-without-wall"),
            pytest.param([_box(empty_weight_grams=None)], id="box-without-weight"),
            pytest.param([_box(inner_height_mm=None)], id="box-without-inner-size"),
            pytest.param(
                [
                    _box(
                        kind="void_fill",
                        fill_volume_ml="500",
                        wall_mm=None,
                    )
                ],
                id="void-fill-with-inner-size",
            ),
            pytest.param(
                [
                    {
                        "key": "void-x",
                        "name": "Void",
                        "kind": "void_fill",
                        "empty_weight_grams": "5",
                        "source": "s",
                    }
                ],
                id="void-fill-without-volume",
            ),
            pytest.param([_box(inner_length_mm="...")], id="placeholder-figure"),
            pytest.param([_box(inner_length_mm=100)], id="json-number-figure"),
            pytest.param([_box(inner_length_mm="0")], id="zero-figure"),
            pytest.param([_box(typical_cost={"AUD": "1.00"})], id="unsupported-currency"),
            pytest.param([_box(typical_cost={"CAD": "..."})], id="placeholder-price"),
            pytest.param([_box(key="Box_Test")], id="key-not-kebab"),
            pytest.param([_box(key="b" * 65)], id="key-too-long"),
            pytest.param([_box(kind="crate")], id="unknown-kind"),
            pytest.param([_box(colour="red")], id="unknown-field"),
        ],
    )
    def test_invalid_catalogues_raise(self, tmp_path, monkeypatch, items):
        path = tmp_path / "packaging.json"
        path.write_text(json.dumps(_catalogue(*items)), encoding="utf-8")
        monkeypatch.setattr(cd, "PACKAGING_CATALOGUE_PATH", path)
        with pytest.raises(cd.CatalogueDataError):
            cd.load_packaging_catalogue()

    def test_unreadable_file_raises(self, tmp_path, monkeypatch):
        path = tmp_path / "packaging.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(cd, "PACKAGING_CATALOGUE_PATH", path)
        with pytest.raises(cd.CatalogueDataError):
            cd.load_packaging_catalogue()

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cd, "PACKAGING_CATALOGUE_PATH", tmp_path / "absent.json")
        with pytest.raises(cd.CatalogueDataError):
            cd.load_packaging_catalogue()


# ============================================
# Tariff validation
# ============================================


class TestTariffValidation:
    def test_a_valid_tariff_loads(self, tmp_path, monkeypatch):
        _write_tariff(tmp_path, _tariff())
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
        loaded = cd.load_tariffs("canada_post")
        assert len(loaded) == 1
        assert loaded[0].services[0].zones[0].brackets[1].max_grams is None

    def test_latest_tariff_is_the_newest_date(self, tmp_path, monkeypatch):
        _write_tariff(tmp_path, _tariff())
        _write_tariff(tmp_path, _tariff(effective_date="2027-01-11"))
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
        assert cd.latest_tariff("canada_post").effective_date.isoformat() == "2027-01-11"

    def test_no_tariff_directory_means_no_tariffs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path / "absent")
        assert cd.load_tariffs() == []

    def _service(self, **overrides) -> dict:
        service = copy.deepcopy(_tariff()["services"][0])
        service.update(overrides)
        return service

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param({"currency": "USD"}, id="wrong-currency-for-carrier"),
            pytest.param({"carrier": "pigeon_post"}, id="unknown-carrier"),
            pytest.param(
                {
                    "services": [
                        {
                            "key": "small_packet",
                            "name": "SP",
                            "zones": [
                                {
                                    "zone": "us",
                                    "brackets": [
                                        {"min_grams": "0", "max_grams": "250", "price": "9"},
                                        {"min_grams": "100", "max_grams": "500", "price": "11"},
                                    ],
                                }
                            ],
                        }
                    ]
                },
                id="overlapping-brackets",
            ),
            pytest.param(
                {
                    "services": [
                        {
                            "key": "small_packet",
                            "name": "SP",
                            "zones": [
                                {
                                    "zone": "us",
                                    "brackets": [
                                        {"min_grams": "0", "max_grams": None, "price": "9"},
                                        {"min_grams": "100", "max_grams": "500", "price": "11"},
                                    ],
                                }
                            ],
                        }
                    ]
                },
                id="open-bracket-not-last",
            ),
            pytest.param(
                {
                    "services": [
                        {
                            "key": "small_packet",
                            "name": "SP",
                            "max_length_mm": "600",
                            "zones": [
                                {
                                    "zone": "us",
                                    "brackets": [
                                        {"min_grams": "0", "max_grams": "100", "price": "9"}
                                    ],
                                }
                            ],
                        }
                    ]
                },
                id="size-limits-not-all-or-none",
            ),
            pytest.param(
                {
                    "services": [
                        {
                            "key": "small_packet",
                            "name": "SP",
                            "zones": [
                                {
                                    "zone": "us",
                                    "brackets": [
                                        {"min_grams": "0", "max_grams": "100", "price": "..."}
                                    ],
                                }
                            ],
                        }
                    ]
                },
                id="placeholder-price",
            ),
            pytest.param(
                {
                    "services": [
                        {
                            "key": "small_packet",
                            "name": "SP",
                            "zones": [
                                {
                                    "zone": "us",
                                    "brackets": [
                                        {"min_grams": "0", "max_grams": "100", "price": "0"}
                                    ],
                                }
                            ],
                        }
                    ]
                },
                id="zero-price",
            ),
        ],
    )
    def test_invalid_tariffs_raise(self, tmp_path, monkeypatch, change):
        data = _tariff(**change)
        folder = tmp_path / "canada_post"
        folder.mkdir()
        (folder / "2026-01-12.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
        with pytest.raises(cd.CatalogueDataError):
            cd.load_tariffs()

    def test_file_name_must_equal_effective_date(self, tmp_path, monkeypatch):
        _write_tariff(tmp_path, _tariff(), name="2026-02-01")
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
        with pytest.raises(cd.CatalogueDataError, match="effective_date"):
            cd.load_tariffs()

    def test_directory_must_name_the_carrier(self, tmp_path, monkeypatch):
        folder = tmp_path / "royal_mail"
        folder.mkdir()
        (folder / "2026-01-12.json").write_text(json.dumps(_tariff()), encoding="utf-8")
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
        with pytest.raises(cd.CatalogueDataError, match="names carrier"):
            cd.load_tariffs()


# ============================================
# carrier_for (research D7)
# ============================================


class TestCarrierFor:
    @pytest.mark.parametrize(
        ("country", "currency", "carrier", "chosen_from", "reason"),
        [
            ("FR", "EUR", "la_poste", "country", None),
            (None, "EUR", "la_poste", "currency", None),
            ("BE", "EUR", None, "country", cd.NO_CARRIER_FOR_COUNTRY),
            ("CA", "USD", None, "country", cd.CARRIER_CURRENCY_MISMATCH),
            (None, "AUD", None, "currency", cd.NO_CARRIER_FOR_CURRENCY),
            ("GB", "GBP", "royal_mail", "country", None),
            ("US", "USD", "usps", "country", None),
            (None, "CAD", "canada_post", "currency", None),
            ("ca", "cad", "canada_post", "country", None),
        ],
    )
    def test_country_first_then_currency(self, country, currency, carrier, chosen_from, reason):
        choice = cd.carrier_for(country, currency)
        assert choice.carrier == carrier
        assert choice.chosen_from == chosen_from
        assert choice.reason == reason

    def test_mismatch_names_the_carrier_considered(self):
        assert cd.carrier_for("CA", "USD").candidate == "canada_post"

    def test_tenant_wrapper_reads_country_and_currency(self):
        class _T:
            country_code = None
            currency_code = "GBP"

        assert cd.carrier_for_tenant(_T()).carrier == "royal_mail"
