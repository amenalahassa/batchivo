# Research: Packaging Advisor

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-25

Every decision below was taken against the code as it stands on `main`
(2026-10-25). No Technical Context item was left as NEEDS CLARIFICATION.

---

## D1 — Where dimensions live, and how their source is recorded

**Decision**: Inline columns on `models`, `products` and `product_variants`:
`length_mm`, `width_mm`, `height_mm` (`Numeric(7,1)`), `dimensions_source`
(`'entered'` | `'measured'`), `dimensions_source_file_id` (FK `model_files`,
`ON DELETE SET NULL`) and `dimensions_set_at` (`timestamptz`). A check
constraint keeps the three dimensions all-null or all-positive, and requires a
source when they are set.

**Rationale**: Dimensions are not cost inputs. The pricing provenance side
table (`pricing_input_provenance`, research 002 D1) exists for cost inputs and
is guarded by `tests/unit/pricing/test_provenance_registry.py`, which already
lists `products.size_cm` and `printers.bed_size_*_mm` under
`NOT_A_COST_INPUT` as "a dimension". Following that precedent keeps the
registry honest. Inline source columns satisfy Constitution VI (provenance
visible, with when it was set) at the cost of three small columns per table.

**Alternatives considered**:
- *Register dimensions in the provenance side table.* Rejected: it would
  claim they are cost inputs, and the registry's vocabulary (`observed`,
  `measured`, `policy`, `assumed`) does not include "entered by the operator",
  which the spec needs (FR-002).
- *One `item_dimensions` table keyed by entity.* Rejected: same no-FK problem
  the provenance table accepted, for no gain.

## D2 — Operator entry wins over measurement (FR-003)

**Decision**: A measurement never writes `models`/`products` dimensions
directly. It is stored on the `model_files` row (D3) and offered. The only
automatic write is when the target has **no** dimensions yet; it then takes
the measurement with `dimensions_source='measured'`. Once an operator saves
dimensions (`'entered'`), a later upload only offers. Adopting an offer is an
explicit operator action that writes `'measured'` with the file id.

**Rationale**: Gives single-part products dimensions with no typing (SC-004)
without ever overwriting an operator's figure.

## D3 — Measuring STL and 3MF without new dependencies

**Decision**: A pure-Python module `app/services/mesh_bounds.py`:
- **Binary STL**: header (80 bytes) + `uint32` count, validated against the
  file length (`84 + 50·n`); `struct.iter_unpack('<12fH', …)` over the
  triangles, tracking min/max of the 9 vertex floats.
- **ASCII STL**: detected when it starts with `solid` **and** the binary length
  check fails (binary files often start with `solid` too); streamed line by
  line, `vertex x y z` lines only.
- **3MF**: open the zip, parse `3D/3dmodel.model` (and any referenced
  `/3D/Objects/*.model`, which Bambu/Orca use) with
  `xml.etree.ElementTree.iterparse`. Per `<object>` gather vertices; for each
  `<build><item>` apply its `transform` (3×4 affine) and any nested
  `<component>` transforms; compute the bounding box of the transformed
  vertices. Apply the model's `unit` attribute (micron, millimeter,
  centimeter, inch, foot, meter) to convert to mm.
- Output: per-object sizes plus the overall build size, as `Decimal` rounded
  to 0.1 mm at the edge. Floats are confined to geometry parsing and never
  touch money (Constitution IV concerns money and rates).

**Size and time limits** (SC-007): files up to 25 MB (~500 k triangles as
binary STL) are measured in the upload request, targeting under 1 s added,
asserted by a timing test on a generated 25 MB STL. Files over 25 MB and up to
200 MB are measured by a Celery task (`mesh_measure.measure_model_file`,
alongside the existing `app/tasks/` modules and worker) after the upload
returns; the response carries `measurement.status = "pending"` and the file
row is updated when the task finishes, which then applies D2. Files over
200 MB are not measured and record a reason. The upload always succeeds
(FR-010).

**Rationale**: `numpy-stl`/`trimesh` would add numpy and native wheels to an
Alpine image for a bounding box. The 3MF zip is already opened by
`model_file_service.parse_3mf_metadata`.

**Alternatives considered**: `trimesh` (heavy, Alpine wheels); reading the
slicer's `plate_N.json` bounding boxes (Bambu-only, and absent from plain
3MFs).

## D4 — Where the measurement is stored

**Decision**: On `model_files`: `measured_length_mm`, `measured_width_mm`,
`measured_height_mm` (overall build), `measured_objects` (JSONB list of
`{name, length_mm, width_mm, height_mm}`), `measured_at`, and
`measurement_note` (why it was not measured, or the multi-object warning).

**Rationale**: Constitution V allows a stored derived figure only with the
invalidation that keeps it honest. A model file's bytes never change after
upload (a new version is a new row), so the measurement cannot go stale; the
invalidation is "the row is deleted". Recomputing would mean downloading the
file from S3 on every read.

## D5 — Packaging attributes on consumables

**Decision**: Extend `consumable_types` with `packaging_kind`
(`'box' | 'mailer' | 'void_fill' | 'wrap'`, nullable), `inner_length_mm`,
`inner_width_mm`, `inner_height_mm` (`Numeric(7,1)`), `empty_weight_grams`
(`Numeric(8,1)`) and `fill_volume_ml` (`Numeric(10,1)`, void fill only).
Constraints: kind in the set; inner dimensions all-null or all-positive;
weights and volumes non-negative. A mailer's `inner_height_mm` is its maximum
usable thickness.

**Rationale**: Boxes are already consumables with cost and stock, and the
product already links one (`products.packaging_consumable_id`). A separate
"box catalogue" table would duplicate stock and cost.

**Provenance registry** (FR-038, Constitution VI): in the MVP the six new
columns decide no cost, so they are listed in `NOT_A_COST_INPUT`. Phase 2
makes `inner_length_mm`, `inner_width_mm`, `inner_height_mm`, `wall_mm` and
`empty_weight_grams` decide postage, so the Phase 2 change moves them out of
`NOT_A_COST_INPUT` into the registry (`consumable_type`,
`default_source="assumed"`), and the consumables API writes their provenance
through the existing provenance service whenever they are saved — the
operator chooses `measured` or `assumed`; an operator's figure is never
labelled `observed`. `fill_volume_ml` stays excluded: it sets a filler
quantity, not a parcel's weight or size. (Void fill's own weight per unit is
not modelled; the parcel weight counts its consumable's `empty_weight_grams`
per unit, which is registered like the others.)

## D6 — The advisor is a pure function

**Decision**: `app/services/packaging_advisor.py` exposes pure functions with
no database access:
`suggest(item: Dims, containers: list[Container], fillers, wraps, clearance,
fragile) -> Advice` and `suggest_for_order(items: list[Dims], …) -> OrderAdvice`.
A thin async loader (`load_packaging_context(db, tenant)`) fetches containers
and settings. All arithmetic in `Decimal`.

**Fit rule**: the item's dimensions plus `2 × clearance` on each axis must be
`≤` the container's inner dimensions for at least one of the 6 axis
permutations. Equality fits (edge case "exactly equal").

**Ranking** (FR-016): in-stock before out-of-stock (`quantity_on_hand > 0`);
then smallest inner volume; then lower `consumable_unit_cost(...)` — the
function costing already uses, so no second cost path — with `None` last; then
name. The advisor returns that cost only as a sort key; the response shows the
cost the product's costing breakdown reports, not one the advisor computed
(FR-021).

**Void fill** (FR-019): empty volume = container inner volume − item box
volume; units = `ceil(empty_ml / fill_volume_ml)`; the void-fill consumable
chosen is the in-stock one with the largest `fill_volume_ml`.

**Minimum box when nothing fits** (FR-018): item dimensions sorted descending,
plus `2 × clearance`.

## D7 — Multi-item packing

**Decision**: A deterministic first-fit-decreasing heuristic over
axis-aligned boxes:
1. Expand each line into units; sort by volume descending.
2. For each candidate container (ranked as D6), try to place every unit using
   a guillotine "extreme points" placement with 6 rotations; accept the first
   container that holds all units.
3. If none holds all, split: repeatedly fill the smallest container that can
   hold the largest remaining unit with as many units as fit, until all are
   placed. Report each parcel's contents.

Clearance applies around the whole group, not between items (items are
wrapped individually when fragile).

**Rationale**: The spec asks for a practical arrangement, not an optimal one
(Assumptions). Order sizes are small (single digits of units), so the search
is trivially fast. Exact 3D bin packing is NP-hard and buys nothing here.

## D8 — Clearance settings

**Decision**: `Tenant.settings["packaging"] = {"clearance_mm": "10.0",
"fragile_clearance_mm": "20.0"}` (decimal strings), read and written through
`GET/PUT /api/v1/settings/packaging`, alongside the existing `/settings/shop`,
`/settings/etsy`. When the key is absent the endpoint returns the defaults
**and labels them as defaults** (`configured: false`); the first PUT writes
them.

**Rationale**: Clearance is not a priced policy, so it does not belong in the
effective-dated `tenant_pricing_policy`. Constitution IV forbids a hardcoded
default *shadowing* a configured value; here the configured value always wins
and the default is visible as such.

## D9 — Postage from the packed parcel (Phase 2)

**Decision**: Extend `app/services/postage.py` — the one postage authority —
rather than adding a module beside it:
- A `Parcel` value (`grams`, optional `outer: Dims`, `reasons`) replaces the
  bare grams argument internally. It is a plain value type defined beside
  `Dims` in `app/services/dims.py`, so `ShippingProfile.covers(parcel)` can
  take it without a model importing from the postage service. **One**
  function assembles it —
  `postage.build_parcel(contents: [(product_weight_g, quantity)],
  packing: [(container, quantity)])` — summing item weights and every packing
  item's `empty_weight_grams × quantity`, and taking the outer size from the
  container (FR-030, Constitution III). Both callers use it: the estimate
  (`postage_for_order`) and dispatch (`OrderParcelService`, D10). Nothing else
  adds packaging weight. A packing item without `empty_weight_grams` makes the
  parcel weight unknown (FR-025), with a reason.
- **Which packing the estimate uses** (FR-025): an order of exactly one unit
  uses that unit's effective accepted packaging (`packaging_quantity` of it);
  any order of more than one unit — several lines, or one line of quantity
  above one — uses `packaging_advisor.suggest_for_order` (D7), one `Parcel`
  per suggested parcel, postage summed. Until order packing ships (US6),
  multi-unit orders keep today's weight-only postage, unchanged and labelled
  `order_packing_unavailable`, rather than an interim guess.
- Carriers measure outside dimensions, but operators know boxes by inner
  size. The parcel's outer size is the container's inner size plus
  `2 × wall_mm` per axis, from one new nullable `wall_mm` column on
  consumables (absent = 0, and the parcel says so). Rejected: three separate
  outer-dimension columns, which double data entry for a few millimetres.
- `ShippingProfile` gains nullable `max_length_mm`, `max_width_mm`,
  `max_height_mm` and `volumetric_divisor`. `covers()` becomes
  `covers(parcel)`: weight bracket on the **chargeable** weight
  (`max(actual, L·W·H[cm³] / divisor · 1000 g)`), and, when limits are set, the
  parcel's sorted dimensions must fit the sorted limits. Profiles without
  limits behave exactly as today (FR-026); a size-limited profile never
  matches a parcel of unknown size (FR-027).
- `_price` keeps its first-match rule with a two-tier order (FR-026):
  size-limited profiles first, by `postage_cost` ascending, so the cheapest
  format the parcel fits wins; then profiles without limits in **today's
  order** (`weight_bracket_min_grams`). A tenant with no size-limited profile
  therefore gets exactly today's choice, which a regression test asserts with
  two weight-only profiles covering the same weight. Rejected: ordering every
  profile by cost, which would silently change existing postage.
- New columns are registered in the provenance registry (`shipping_profile`,
  `default_source="policy"`), since they decide a cost.
- Effective dating (FR-029) already exists (`effective_from/effective_to`,
  T233); the new columns ride on it — a change supersedes the row.

## D10 — Confirming the parcel at dispatch (Phase 2)

**Decision**: New table `order_parcels` (one row per physical parcel) with
`order_parcel_items` (consumable, quantity) — written once by
`POST /api/v1/orders/{id}/parcels`, refused (409) if the order already has
parcels. On write:
1. Each confirmed parcel is assembled by `postage.build_parcel` (D9) from the
   order's line weights and the confirmed items; the stored
   `outer_*`/`packed_weight_grams` are its output, not a second calculation.
   The postage for the confirmed parcels (summed) is computed by `postage.py` and, if
   `orders.postage_paid` was not `entered` by a person, replaces the checkout
   estimate with `actuals_source='derived'`. An operator-entered postage
   (`ship_order`'s `postage_paid`) always wins.
2. One `consumable_usage` row per container/filler with `usage_type='shipping'`
   and an `order_id` (new nullable FK) and `quantity_on_hand` reduced; negative
   stock is allowed and reported (FR-037).
3. Idempotency: a unique constraint on `order_parcels(order_id, sequence)` and
   the 409 guarantee a second confirmation deducts nothing.

The endpoint is separate from `POST /orders/{id}/ship` because WooCommerce
orders return early from `ship_order` through `dispatch_native_commerce`; a
separate call works for every order source. The ship dialog calls it first.

**Rationale**: History immutable (Constitution VI): the parcel and its usage
are written once. `actuals_source` vocabulary (`entered`/`ingested`/`derived`)
is reused rather than extended.

## D11 — Variant overrides (clarification Q1)

**Decision**: `product_variants` gains the D1 dimension columns plus
`packaging_consumable_id` and `packaging_quantity` (nullable = inherit).
Effective values resolve variant → product in one helper
(`effective_dimensions`, `effective_packaging`) used by the advisor and by
postage. Order items carry no variant id; a line resolves to a variant when
its `product_sku` equals a variant's `sku`, otherwise to the product.

**Known limit**: `costing.py` has no notion of variants today (variants carry
their own legacy pence overrides). The variant packaging override therefore
affects packing and postage but not the cost breakdown, which continues to
show the product's packaging line. Nothing diverges, because no variant cost
is computed anywhere; teaching costing about variants is outside this feature.
So that two screens never appear to disagree (FR-039), a variant whose
packaging differs from the product's carries
`packaging_notes: ["variant_packaging_not_costed"]` in its response, and the
variant row says "Cost breakdown uses the product's packaging". No screen
computes or shows a variant packaging cost.

## D12 — Printer-bed fit and Etsy (Phase 2)

**Decision**:
- `PrintQueueService._is_printer_compatible`: when the model has dimensions
  and the printer has all three bed sizes, require
  `height ≤ bed_z` and the footprint to fit `bed_x × bed_y` in either
  horizontal rotation. Missing data on either side → current behaviour. The
  existing per-printer config shortcut stays first (an explicit config is the
  operator's statement that it fits).
- `etsy_sync`: emit `Size: L × W × H mm` when the product's effective
  dimensions are set, else the existing `size_cm` line.

## D13 — Migrations

**Decision**: Two Alembic revisions, one per phase, chained on whatever the
head is when implementation starts (today `rls_uncovered_tenant_tables_v1`,
which is uncommitted on `main` — rebase the `down_revision` if that changes).
New tables (`order_parcels`, `order_parcel_items`) get
`ENABLE ROW LEVEL SECURITY` and `tenant_isolation_policy` in the same revision;
`tests/integration/test_every_tenant_table_has_rls.py` then covers them
automatically. All other changes are nullable column additions: no data
backfill, no computed values change (so the constitution's per-record diff
report is not triggered by the MVP migration). The Phase 2 postage change *does*
change computed postage for future quotes; the plan ships a delta report for
products' indicative postage (see quickstart).
