# API Contracts: Packaging Advisor

Base: `/api/v1`. All endpoints require a JWT, resolve the tenant via
`get_current_tenant`, and use `get_tenant_db`. Writes require member role or
above (`RequireMember`); viewers get 403. Lengths, weights and volumes travel
as **decimal strings** (`"120.0"`), like money.

Every endpoint's tests cover 200/201, 401, 403 (viewer, writes only), 422 and
404 (Constitution II).

---

## MVP

### Dimensions on existing resources

`ProductResponse`, `ModelResponse`, `ProductVariantResponse` gain:

```json
"dimensions": {
  "length_mm": "120.0", "width_mm": "80.0", "height_mm": "45.0",
  "source": "entered",            // "entered" | "measured" | null
  "source_file_id": null,
  "set_at": "2026-10-25T10:00:00Z",
  "inherited": false              // variants only: true when showing the product's
}
```

`ProductResponse` also gains `"is_fragile": false`. Variants gain
`packaging_consumable_id`, `packaging_quantity` (null = inherited),
`effective_packaging`, and `packaging_notes` — `["variant_packaging_not_costed"]`
when the variant's packaging differs from the product's (FR-039).

### `PUT /products/{id}/dimensions` · `PUT /models/{id}/dimensions` · `PUT /products/{id}/variants/{variant_id}/dimensions`

Request:
```json
{ "length_mm": "120.0", "width_mm": "80.0", "height_mm": "45.0",
  "adopt_file_id": null }
```
- With `adopt_file_id`: copies that file's measurement, `source="measured"`.
  The file must belong to the model (or to the product's single model).
- Without: `source="entered"`.
- `null` for all three clears dimensions (variants: back to inherited).
- 422: zero, negative, non-numeric, more than one decimal place, or only some
  of the three given.

Response: the `dimensions` object.

### `PATCH /products/{id}` — existing

Accepts `is_fragile`.

### Model file upload — existing `POST /models/{model_id}/files`, `POST /files/parse-3mf`

`ModelFileUploadResponse` and `ThreeMFParseResponse` gain:
```json
"measurement": {
  "length_mm": "40.0", "width_mm": "30.0", "height_mm": "20.0",
  "objects": [{"name": "Body", "length_mm": "40.0", "width_mm": "30.0", "height_mm": "20.0"}],
  "note": null,
  "status": "done",             // "done" | "pending" (> 25 MB, measured after upload) | "skipped" | "failed"
  "applied_to": ["model"]       // which records took it automatically (empty when only offered)
}
```
`measurement` is `null` for G-code. An unreadable mesh returns
`status: "failed"` with a note; a file over 25 MB returns `status: "pending"`
and no sizes, and the file list shows them once the background measurement
finishes. The upload always returns 201.

### Consumables — existing `POST/PATCH /consumables`, `GET /consumables`

Accept and return `packaging_kind`, `inner_length_mm`, `inner_width_mm`,
`inner_height_mm`, `wall_mm`, `empty_weight_grams`, `fill_volume_ml`.
Phase 2 (FR-038): requests may carry
`"packaging_provenance": {"source": "measured" | "assumed"}` (default
`assumed`), written for inner dims, wall and empty weight; responses carry each
of those fields' provenance as the existing provenance endpoints report it.
`GET /consumables?packaging_kind=box,mailer` filters. Response adds
`"packaging_incomplete": true` for a box/mailer missing an inner dimension.

### `GET /settings/packaging` · `PUT /settings/packaging`

```json
{ "clearance_mm": "10.0", "fragile_clearance_mm": "20.0", "configured": false }
```
PUT body omits `configured`; values `>= 0`, one decimal place.

### `GET /products/{id}/packaging-suggestions?variant_id=`

Response 200:
```json
{
  "item": {"length_mm": "120.0", "width_mm": "70.0", "height_mm": "30.0", "source": "entered"},
  "clearance_mm": "10.0",
  "fragile": false,
  "suggestions": [
    {
      "consumable_id": "…", "name": "Box S", "kind": "box", "in_stock": true,
      "inner": {"length_mm": "150.0", "width_mm": "100.0", "height_mm": "60.0"},
      "orientation": ["length", "width", "height"],
      "room_mm": {"length": "10.0", "width": "10.0", "height": "10.0"},
      "empty_volume_ml": "648.0",
      "void_fill": {"consumable_id": "…", "name": "Paper fill", "quantity": 1},
      "wrap": null,
      "is_current": false
    }
  ],
  "minimum_inner": null,
  "warnings": []
}
```
- No dimensions → 200 with `suggestions: []` and warning
  `"dimensions_required"` (not an error: the screen shows a prompt).
- Nothing fits → `suggestions: []`, `minimum_inner` set, warning
  `"nothing_fits"`.
- No cost field: the product's packaging cost is read from the existing cost
  breakdown (FR-021).

### `POST /products/{id}/packaging` — accept

```json
{ "consumable_id": "…", "quantity": 1, "variant_id": null }
```
Sets `packaging_consumable_id`/`packaging_quantity` on the product, or on the
variant when `variant_id` is given. 422 if the consumable is not a box/mailer.
Does **not** require the container to fit (the operator may override); the
product then shows warning `"accepted_packaging_does_not_fit"` (FR-024) in
`GET …/packaging-suggestions` and in `ProductResponse.packaging_warnings`.

---

## Phase 2

### Shipping profiles — existing `/shipping-profiles`

Accept and return `max_length_mm`, `max_width_mm`, `max_height_mm`,
`volumetric_divisor`. Changing them on a profile in force supersedes it
(existing T233 behaviour).

### `GET /orders/{id}/packaging-suggestions`

```json
{
  "parcels": [
    {"consumable_id": "…", "name": "Box M",
     "contents": [{"product_id": "…", "sku": "DRG-01", "quantity": 2}],
     "outer_mm": {"length_mm": "206.0", "width_mm": "156.0", "height_mm": "106.0"},
     "packed_weight_grams": "460.0",
     "void_fill": {"consumable_id": "…", "quantity": 2}}
  ],
  "estimated_postage": {"amount": "3.95", "zone": "domestic", "reason": null, "is_estimate": true},
  "warnings": []
}
```
A line without dimensions → `parcels: []`, warning
`{"code": "dimensions_required", "sku": "…"}`.

### `POST /orders/{id}/parcels` — confirm at dispatch

```json
{ "parcels": [
    {"items": [{"consumable_id": "…", "quantity": 1},
               {"consumable_id": "<void fill>", "quantity": 2}]}
] }
```
- 201: the stored parcels, the postage they determine, and stock warnings
  (`{"code": "stock_below_zero", "consumable_id": "…", "on_hand": -1}`).
- 409 when the order already has parcels (written once; FR-036/037).
- Writes `consumable_usage` rows (`usage_type="shipping"`, `order_id`) and
  lowers `quantity_on_hand`.
- Sets `orders.postage_paid` from the confirmed parcels with
  `actuals_source="derived"` unless it is already `"entered"`.

### `GET /orders/{id}` — existing

`OrderResponse` gains `parcels` (as stored) and `postage_is_estimate`
(true while no parcel is confirmed and postage is derived).
