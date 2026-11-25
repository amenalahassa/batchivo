# Phase 0 Research: 3MF Import Auto-Fill

## 1. Bambu Studio / OrcaSlicer embedded slice metadata

**Decision**: Parse `Metadata/slice_info.config` (XML) from the uploaded
`.3mf` zip archive — the same archive already opened by
`extract_3mf_thumbnail()` in `backend/app/services/model_file_service.py`.

**Structure** (per community documentation of the Bambu/Orca 3MF project
format):

- Root `<config>` element containing a `<header>` and one or more `<plate>`
  elements.
- Each `<plate>` has `<metadata key="..." value="...">` children, notably:
  - `index` — 1-based plate number
  - `prediction` — estimated print time **in seconds**
  - `weight` — total filament weight **in grams** for that plate
- Each `<plate>` has `<filament id=".." used_g=".." used_m=".." type=".."
  color=".." />` children for per-slot filament usage within that plate.

**Rationale**: This file is only present in a `.gcode.3mf` (i.e. the project
was actually sliced before export, not just saved unsliced) — consistent
with Story 2's fallback requirement, since an unsliced export simply won't
have this file and the parser already needs a "metadata not found" path.

**Alternatives considered**: Parsing `Metadata/project_settings.config`
instead — rejected because it reflects *configured* filaments for the whole
project, not *actual per-plate usage*, which would misreport weight when a
project defines more filament slots than a given plate uses.

**Caveat**: This structure is based on third-party/community documentation,
not an official Bambu Lab/OrcaSlicer spec. Implementation must validate
against real sample files from both slicers before trusting exact tag names
in production, and must fail soft (Story 2) on any mismatch rather than
crash.

## 2. PrusaSlicer embedded slice metadata

**Decision**: Attempt a best-effort parse of `Metadata/Slic3r_PE.config`
(INI-style key=value config), but treat PrusaSlicer support as
**unreliable by nature**, not a fully equivalent second code path to
Bambu/Orca.

**Rationale**: `Slic3r_PE.config` / `Slic3r_PE_model.config` primarily store
pre-slice *project settings and object placement* — a snapshot for
reopening the project in PrusaSlicer — not confirmed to reliably contain
computed print-time/weight *results* the way Bambu/Orca's
`slice_info.config` does. PrusaSlicer's computed time/weight estimates are
most reliably available in exported G-code, not necessarily the `.3mf`
project file.

**Implication for the feature**: For PrusaSlicer files, the system should
still attempt the parse (satisfying FR-001's "attempt to support
PrusaSlicer"), but Story 2's graceful-fallback path (blank fields, no crash)
is expected to be the **common case** for PrusaSlicer uploads, not an edge
case. This does not change any functional requirement — it changes the
*expected hit rate*, which is an implementation/tuning concern, not a spec
change.

**Alternatives considered**: Dropping PrusaSlicer entirely from scope —
rejected; FR-001 already treats it as "attempt, fall back gracefully if
unparseable," which this finding doesn't violate, it just sets a realistic
expectation.

## 3. Parsing approach

**Decision**: Extend `model_file_service.py` with a new pure function
`parse_3mf_metadata(file_content: bytes) -> ThreeMFParseResult` that:
1. Opens the same `zipfile.ZipFile` the thumbnail extractor already opens
   (single zip-open per upload — avoid opening twice).
2. Tries the Bambu/Orca path (`Metadata/slice_info.config`, XML).
3. Falls back to the PrusaSlicer path (`Metadata/Slic3r_PE.config`) if the
   first yields nothing.
4. Returns a result object with whichever fields were found; all fields
   are `Optional` and independently nullable (FR-007).
5. Never raises for malformed/missing metadata — mirrors
   `extract_3mf_thumbnail()`'s existing `try/except zipfile.BadZipFile` /
   broad `except Exception` pattern, logs at `warning`/`debug` level per
   existing convention.

**Rationale**: Reuses the exact architectural pattern already proven for
thumbnail extraction (stdlib `zipfile`, no new dependency, fail-soft by
design) rather than introducing a new parsing library.

**Alternatives considered**: A third-party 3MF/slicer-metadata parsing
library — rejected; no such library is already a project dependency, the
format needed (XML/INI inside a zip) is fully handled by the stdlib
(`zipfile` + `xml.etree.ElementTree` + `configparser`), and adding a
dependency for ~2 small parsers is unjustified complexity.

## 4. Where parsing happens in the request flow

**Decision**: Add a new endpoint, independent of any existing `model_id`,
that accepts a `.3mf` upload and returns the parse result without touching
the database. The existing `POST /{model_id}/files` upload endpoint
*requires* the model to already exist (confirmed in
`backend/app/api/v1/model_files.py`), so it cannot be the vehicle for
pre-filling the *creation* form — the model doesn't exist yet at that point.

**Rationale**: Matches FR-003/FR-004 — parsing must be possible before a
model record exists, purely to suggest form values.

**Alternatives considered**: Making `model_id` optional on the existing
upload endpoint — rejected; that endpoint's contract (store a `ModelFile`
row) doesn't apply pre-creation, and overloading it would conflate "parse
only" with "upload and persist," violating FR-003's "without creating or
modifying a model record... on upload alone."

## 5. Carrying the weight suggestion to BOM entry

**Decision**: The frontend holds the parsed result in memory (component
state) from the moment of upload through model creation, and passes the
suggested weight into the first "add material" interaction on the newly
created model's detail page — no backend persistence of the suggestion is
needed, since BOM entry for a brand-new model typically happens in the same
session immediately after creation.

**Rationale**: Keeps the backend stateless for this transient data (FR-003
already prohibits persisting a parse result on its own); avoids a new table
or cache entry for a value that only needs to survive one client session.

**Alternatives considered**: Persisting the parse result server-side keyed
by a token, to survive across sessions/reloads — rejected as over-engineered
for the stated value (a convenience suggestion, not critical data); the
maker can always just type the weight if they navigate away before adding
BOM lines.
