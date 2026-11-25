# Contract: Catalogue Data Files

Files under `backend/app/data/` are loaded by `services/catalogue_data.py` and validated with
Pydantic. A unit test loads every file; an invalid file fails CI.

## packaging_catalogue.json

```json
{
  "version": 1,
  "as_of": "2026-11-01",
  "items": [
    {
      "key": "box-s-150x100x50",
      "name": "Box S 150 × 100 × 50 mm",
      "kind": "box",
      "inner_length_mm": "150", "inner_width_mm": "100", "inner_height_mm": "50",
      "wall_mm": "3",
      "empty_weight_grams": "60",
      "unit_of_measure": "each",
      "typical_cost": {"CAD": "0.95", "GBP": "0.55", "USD": "0.70", "EUR": "0.60"},
      "source": "<supplier, product reference, date>"
    },
    {
      "key": "void-paper-roll",
      "name": "Kraft paper void fill",
      "kind": "void_fill",
      "fill_volume_ml": "500",
      "empty_weight_grams": "8",
      "unit_of_measure": "each",
      "typical_cost": {"CAD": "0.05"},
      "source": "<...>"
    }
  ]
}
```

Rules: keys unique; box/mailer need all three inner sizes, wall and empty weight; void_fill/wrap
need `fill_volume_ml` and no inner size; decimals as strings > 0; currencies limited to CAD, GBP,
USD, EUR. Bumping `version` is required for any change to existing entries.

## postage_tariffs/<carrier>/<YYYY-MM-DD>.json

```json
{
  "carrier": "canada_post",
  "name": "Canada Post",
  "currency": "CAD",
  "effective_date": "2026-01-12",
  "source": "Canada Post — Postage rates and prices, effective 2026-01-12, <URL>",
  "services": [
    {
      "key": "small_packet",
      "name": "Small Packet",
      "max_length_mm": "600", "max_width_mm": "400", "max_height_mm": "400",
      "volumetric_divisor": null,
      "zones": [
        {"zone": "us", "brackets": [
          {"min_grams": "0", "max_grams": "100", "price": "..."},
          {"min_grams": "100", "max_grams": "250", "price": "..."}
        ]}
      ]
    }
  ]
}
```

Rules: file name date equals `effective_date`; `carrier` equals the directory; currency fixed per
carrier (CAD, GBP, EUR, USD); per zone, brackets ascending and non-overlapping, the last may have
`max_grams: null`; size limits all-or-none; prices > 0. The numbers are transcribed from the
named source during implementation and reviewed (see tasks); placeholders are not allowed in a
shipped file.
