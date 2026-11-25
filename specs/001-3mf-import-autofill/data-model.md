# Phase 1 Data Model: 3MF Import Auto-Fill

No migration, no new table, and no new column. This feature adds one
**transient (request/response only)** shape and changes zero persisted
schema. Existing entities are listed only to show exactly where parsed
values eventually land once the maker saves.

## New transient shape: 3MF Parse Result

Exists only for the duration of one upload→response round trip. Never
written to the database.

| Field | Type | Notes |
|---|---|---|
| `print_time_minutes` | `Optional[int]` | Total minutes, derived from the slicer's seconds-based estimate (FR-002). Null if not found/unparseable (FR-007). |
| `filament_weight_grams` | `Optional[float]` | Aggregate weight across filament slots for the selected plate (FR-002, FR-002a). Null if not found. |
| `plate_count` | `Optional[int]` | Total plates in the file (FR-002, FR-008). Null only if the file has no parseable plate metadata at all. |
| `source_plate_index` | `Optional[int]` | Which plate `print_time_minutes`/`filament_weight_grams` were taken from when `plate_count > 1` (FR-008). |
| `slicer_detected` | `Optional[str]` | One of `"bambu_orca"`, `"prusaslicer"`, or `None` if unrecognized (Story 2/Edge Cases). Informational only — not a form field. |
| `thumbnail_available` | `bool` | Whether `extract_3mf_thumbnail()` also found a thumbnail in this same file (FR-006) — lets the frontend show one combined "what we found" summary instead of two separate calls. |

Validation rules:
- Every numeric field is independently nullable; a parse failure on one
  field never blocks the others (FR-007).
- `print_time_minutes` and `filament_weight_grams`, when present, MUST be
  `> 0`; a parsed `0` or negative value is treated as unparseable and
  nulled out before returning (Edge Cases).
- No persistence: this shape is a Pydantic response schema, not a
  SQLAlchemy model.

## Existing entities touched (read-only context, no schema change)

### Model (`backend/app/models/model.py`)
Already has the two fields this feature pre-fills:
- `print_time_minutes: Optional[int]`
- `prints_per_plate: int` (default `1`) — mapped from `plate_count` when
  the maker accepts the suggestion; the maker can still override it.

No new column is added here.

### ModelMaterial (`backend/app/models/model_material.py`)
Already has the field that `filament_weight_grams` suggests a value for:
- `weight_grams: float` (required, non-null on this entity)

This entity also requires `spool_id` and `cost_per_gram`, neither of which
this feature can supply — the maker still selects the spool and the system
still snapshots its current cost-per-gram as it does today. This feature
only pre-fills the `weight_grams` input in that existing flow (FR-004a).

## State transitions

None. There is no new stateful entity — the parse result is computed fresh
on every upload and discarded once the frontend has read it into form
state (research.md §5).
