# Quickstart: Validating the Packaging Advisor

Contracts: [contracts/packaging-api.md](./contracts/packaging-api.md) ·
Data: [data-model.md](./data-model.md)

## Prerequisites

```bash
cd backend && poetry run alembic upgrade head
cd backend && poetry run uvicorn app.main:app --reload
cd frontend && npm run dev
```

Test fixtures live under `backend/tests/fixtures/meshes/`: a 40 × 30 × 20 mm
block as binary STL, ASCII STL, a plain 3MF, a 3MF whose build item is
rotated 90° and scaled 2×, a 3MF in inches, and a two-object 3MF.

## Automated checks

```bash
cd backend && poetry run pytest tests/unit/test_mesh_bounds.py tests/unit/test_packaging_advisor.py tests/unit/test_postage_parcel.py -q
cd backend && poetry run pytest tests/api/test_packaging_api.py tests/api/test_order_parcels_api.py -q
cd backend && poetry run pytest tests/unit/pricing/test_provenance_registry.py -q
cd backend && poetry run pytest && poetry run ruff check
cd frontend && npm test && npm run lint && npm run typecheck
```

`test_every_tenant_table_has_rls.py` needs a PostgreSQL `DATABASE_URL`
(`docker-compose.test.yml`).

## Manual scenarios

### MVP

1. **Dimensions** (Story 1): open a product → Dimensions → enter
   120 × 80 × 45 → save. Expect "Entered · today". Enter `0` → field error.
2. **Measure** (Story 3): on a model with no dimensions, upload the block STL.
   Expect 40.0 × 30.0 × 20.0, "Measured from block.stl". Enter other values,
   upload again → entered values stay, the measurement appears as an offer.
3. **Rotated 3MF**: upload the rotated/scaled 3MF → 60.0 × 80.0 × 40.0
   (2× scale, X/Y swapped). Upload a 30 MB STL → the upload returns at once
   with "Measuring…", and the size appears when the worker finishes (SC-007).
4. **Box catalogue**: add boxes 100×100×50, 150×100×60, 200×150×100 (kind box,
   weights 30/40/80 g), and a void fill with 1000 ml per unit.
5. **Suggest** (Story 2): product 120 × 70 × 30, clearance 10 → ranking
   150×100×60, then 200×150×100; 100×100×50 absent. Void fill 1 unit
   (648 ml empty). Accept the first → product packaging set; cost breakdown
   shows the box's packaging line from costing.
6. **Nothing fits**: product 300 × 300 × 300 → "Nothing fits", minimum inner
   320 × 320 × 320.
7. **Fragile** (Story 4): mark fragile with fragile clearance 20 → 150×100×60
   no longer offered (needs 160 × 110 × 70).
8. **Drift warning**: change the product to 160 × 100 × 50 → product page
   warns the accepted box no longer fits.
9. **Variant**: on size variant L, enter 180 × 120 × 60 → suggestions for L
   differ from the product's; accept → variant shows its own packaging and
   "Cost breakdown uses the product's packaging"; other variants still inherit.
10. **Viewer**: as a viewer, the Accept and Save buttons are absent; the API
    returns 403.

### Phase 2

11. **Packed weight** (Story 5): product 180 g with a 40 g box → product's
    indicative postage uses the 220 g bracket. The box's weight shows its
    source (Measured / Estimated). A tenant with only weight-only profiles
    sees the same profile chosen as before.
12. **Size class**: profiles "Large letter" (≤ 750 g, 353×250×25, £2.70) and
    "Small parcel" (≤ 2 kg, 450×350×160, £3.95). Product in a 30 mm deep box
    → Small parcel chosen.
13. **Volumetric**: courier profile divisor 5000; parcel 400×300×200 at 1 kg →
    chargeable 4.8 kg bracket.
14. **Order box** (Story 6): order of two products that fit together → one
    parcel suggested with both; add a third that cannot fit → split.
15. **Dispatch** (FR-036/037): confirm parcel with a different box than
    suggested → order postage recomputed from the confirmed box, box stock −1,
    void fill stock −2; confirm again → 409, stock unchanged.
16. **History**: an order shipped before Phase 2 keeps its `postage_paid`.
17. **Printer bed** (Story 7): model 300 mm long, printer bed 256 → that
    printer is not matched; model without dimensions → matched as before.
18. **Etsy**: sync a product with dimensions → description shows
    "Size: 120 × 80 × 45 mm".

## Phase 2 delta report

Before the Phase 2 release is accepted (task T056), run the indicative-postage delta for every product (old
weight-only vs packed parcel) and attach it to the release note, per the
constitution's rule for changes to computed values:

```bash
cd backend && poetry run python -m scripts.postage_delta_report
```
