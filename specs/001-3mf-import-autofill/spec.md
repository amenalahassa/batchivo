# Feature Specification: 3MF Import Auto-Fill

**Feature Branch**: `001-3mf-import-autofill`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "3MF import auto-fill — parse print time, filament weight, and plate count out of uploaded .3mf slicer files (Bambu Studio/OrcaSlicer/PrusaSlicer) and pre-fill the model creation form, instead of requiring the maker to re-type numbers the slicer already computed."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pre-fill model form from an uploaded 3MF (Priority: P1)

A maker creating a new model uploads the `.3mf` file exported by their slicer
(Bambu Studio, OrcaSlicer, or PrusaSlicer) as the first step of model
creation. The system parses the embedded slicer metadata and pre-fills print
time (hours/minutes) and plate count on the model form. The maker reviews
the pre-filled values, corrects anything slicer-specific or wrong, and saves
— without hand-typing numbers the slicer already computed. (Filament weight
is also parsed in this step, but — because the model form has no plain
weight field — it is carried forward as a suggestion for the separate
material/BOM step; see User Story 1a.)

**Why this priority**: This is the core value of the feature — it is the
only story that removes manual data entry. Without it, the feature delivers
nothing.

**Independent Test**: Upload a known-good `.3mf` from each supported slicer
to the model creation flow and confirm print time and plate count fields are
pre-filled with values matching the slicer's own summary screen, and that
the maker can still edit every field before saving.

**Acceptance Scenarios**:

1. **Given** a maker is on the model creation form, **When** they upload a
   valid Bambu Studio or OrcaSlicer `.3mf` file, **Then** the print time and
   plate count fields are pre-filled from the file's embedded metadata and
   the thumbnail is extracted as before.
2. **Given** a maker is on the model creation form, **When** they upload a
   valid PrusaSlicer `.3mf` file, **Then** the same fields are pre-filled
   using PrusaSlicer's metadata layout when present.
3. **Given** the form has been pre-filled from a `.3mf` upload, **When** the
   maker edits a pre-filled field before saving, **Then** their edited value
   is what gets saved, not the parsed value.

---

### User Story 1a - Carry parsed weight to the material/BOM step (Priority: P1)

Immediately after saving the model created in User Story 1, the maker adds a
material (filament/spool) usage entry for it. The weight parsed from the
same `.3mf` upload is pre-filled as the suggested weight, with no spool
pre-selected — the maker still picks which physical spool was used, but
doesn't have to re-read the slicer's weight number and retype it.

**Why this priority**: Same P1 as User Story 1 — it is the other half of
"don't retype numbers the slicer already computed" from the original gap
report. Split out as its own story only because it touches a different
screen/component (the BOM editor, not the model form) and has its own
independent test.

**Independent Test**: Create a model from a `.3mf` with a known filament
weight (User Story 1), then open the material/BOM entry step for that model
and confirm the weight field is pre-filled with the parsed value while the
spool selector starts empty/unselected.

**Acceptance Scenarios**:

1. **Given** a model was just created from a `.3mf` upload with a parsed
   filament weight, **When** the maker opens the add-material step for that
   model, **Then** the weight field is pre-filled with the parsed value and
   no spool is pre-selected.
2. **Given** the weight field has been pre-filled this way, **When** the
   maker edits it before saving the material entry, **Then** their edited
   value is what gets saved.
3. **Given** a model was created from a `.3mf` with no parseable weight
   (Story 2), **When** the maker opens the add-material step, **Then** the
   weight field behaves exactly as it does today (blank, manual entry).

---

### User Story 2 - Graceful fallback when metadata can't be parsed (Priority: P2)

A maker uploads a `.3mf` file that is malformed, from an unsupported/unknown
slicer, or missing some of the expected metadata (e.g. no filament weight
recorded). The system still extracts the thumbnail (existing behavior),
leaves the fields it couldn't determine blank for manual entry, and does not
block model creation or throw an unhandled error.

**Why this priority**: The parser cannot cover every slicer/version
combination. Without this story, an edge-case file would break model
creation entirely, which is worse than today's fully-manual baseline.

**Independent Test**: Upload a `.3mf` with corrupted/missing slicer config
XML and confirm the model creation flow still completes — thumbnail (if
present) is extracted, parseable fields are filled, unparseable fields are
left blank, and the maker sees no crash or unhandled error.

**Acceptance Scenarios**:

1. **Given** a `.3mf` file with no recognizable slicer metadata, **When** it
   is uploaded, **Then** the form falls back to the current fully-manual
   entry with no pre-filled fields, and the thumbnail is still extracted if
   present.
2. **Given** a `.3mf` file missing only filament weight data, **When** it is
   uploaded, **Then** print time and plate count are pre-filled while weight
   is left blank for manual entry.
3. **Given** a file with an extension outside the system's allowed 3D-file
   types (e.g. `.step`), **When** it is uploaded, **Then** it is rejected
   with a clear error message exactly as it is today — no parsing is
   attempted.
4. **Given** a file with a `.3mf` extension whose content is actually
   corrupted or not a real zip archive, **When** it is uploaded, **Then**
   the system does not crash or reject the upload — it falls back to the
   same all-blank, manual-entry state as a valid-but-unrecognized file
   (consistent with how thumbnail extraction already handles this case).

---

### User Story 3 - Multi-plate and multi-object files (Priority: P3)

A maker uploads a `.3mf` file that contains multiple plates or multiple
named objects/parts in a single plate. The system surfaces the per-plate
print time and plate count so the maker isn't forced to assume a single-plate
file.

**Why this priority**: Multi-plate files are common for batch printing but
are a secondary refinement — single-plate parsing (P1) already covers the
majority case described in the originating gap report.

**Independent Test**: Upload a `.3mf` with 3 plates and confirm the parsed
plate count reflects 3, and the pre-filled print time corresponds to the
plate the system selects (see FR-008 for which plate is used when multiple
exist).

**Acceptance Scenarios**:

1. **Given** a `.3mf` file with multiple plates, **When** it is uploaded,
   **Then** the pre-filled plate count matches the number of plates in the
   file.
2. **Given** a `.3mf` file with multiple plates, **When** the system cannot
   unambiguously pick one plate's print time/weight to pre-fill, **Then** it
   pre-fills from the first plate and leaves the rest for manual review
   (documented in Assumptions).

### Edge Cases

- What happens when the uploaded file has a `.3mf` extension but its content
  is actually a different/corrupted file (not a real zip archive)? → Not
  rejected outright — falls back to the same all-blank result as a
  valid-but-unrecognized file (Story 2), matching how thumbnail extraction
  already treats a bad zip today. Only a *wrong extension* (e.g. `.step`)
  is rejected before parsing is attempted.
- What happens when parsed print time is `0` or negative (bad slicer data)?
  → Treated as unparseable; field left blank rather than saving a nonsense
  value.
- What happens when the file is a valid 3MF but was exported by a slicer the
  system doesn't recognize at all (e.g. Cura)? → Falls back to thumbnail-only
  extraction (Story 2), same as a malformed file.
- What happens if the maker uploads a 3MF *after* already manually typing
  values into the form? → Newly parsed values overwrite blank fields only;
  fields the maker already edited are not silently overwritten (see
  FR-007).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST parse embedded slicer metadata from an uploaded
  `.3mf` file for Bambu Studio, OrcaSlicer, and PrusaSlicer, in addition to
  the existing thumbnail extraction.
- **FR-002**: System MUST extract, when present in the file: estimated print
  time, total filament weight (grams), and plate count.
- **FR-002a**: Parsed filament weight MUST be kept available for use later
  as a suggested value when the maker records which material was used,
  since the model record itself has no plain weight field to pre-fill (see
  Key Entities).
- **FR-003**: System MUST return parsed values as suggested initial values
  only, without creating or modifying a model record, or a material/BOM
  entry, on upload alone.
- **FR-004**: The model creation form MUST accept an uploaded `.3mf` file as
  part of the creation flow (not only as a secondary post-creation action)
  and pre-fill print time and plate count fields from the parse result.
- **FR-004a**: When the maker proceeds to record which material (spool) and
  how much of it was used for the model, the parsed filament weight MUST be
  offered as a pre-filled suggestion for the weight entry, without
  pre-selecting which spool — spool selection remains a manual choice (see
  Assumptions on why auto-matching a spool is out of scope).
- **FR-005**: The maker MUST be able to review and edit every pre-filled
  field before saving; saved values MUST reflect the maker's final edits, not
  the raw parsed values.
- **FR-006**: System MUST continue to extract and attach the thumbnail
  exactly as it does today, regardless of whether metadata parsing succeeds.
- **FR-007**: When a field cannot be parsed (missing, malformed, or
  unsupported slicer), system MUST leave that field blank for manual entry
  rather than failing the whole upload; already-edited form fields MUST NOT
  be overwritten by a later parse result.
- **FR-008**: When a `.3mf` file contains multiple plates, system MUST
  report the total plate count and pre-fill print time/weight from the
  first plate in the file.
- **FR-009**: System MUST reject, before attempting to parse, any file whose
  *extension* is outside the system's existing allowed 3D-file types — the
  same error handling path used for other invalid file uploads today. A
  file with a valid `.3mf` extension whose *content* turns out to be
  corrupted/not a real zip archive is explicitly NOT rejected this way — it
  falls back to Story 2's all-blank result instead (matching existing
  thumbnail-extraction precedent).
- **FR-010**: System MUST NOT regress existing thumbnail-only upload
  behavior for any `.3mf` file that was previously supported.

### Key Entities *(include if feature involves data)*

- **3MF Parse Result**: Transient (non-persisted) result of parsing an
  uploaded file — estimated print time, filament weight, plate count,
  per-plate breakdown, and which fields were successfully determined vs.
  left blank. Exists only for the duration of the upload-to-form round trip;
  not stored unless the maker saves the model.
- **Model** (existing entity): Gains no new persisted fields for print time
  or plate count — `print_time_minutes` and `prints_per_plate` already exist
  on the model record today; this feature only changes how those two fields
  get their initial values.
- **Material usage entry** (existing entity, today called "BOM line"):
  There is **no plain "filament weight" field on Model** — weight is only
  ever recorded as part of a material usage entry, which also requires
  picking which specific spool (a tenant's actual physical/catalog material)
  was used and its cost. This entry is created in a separate step (today:
  after the model already exists), not on the model creation form.
  Auto-filling weight therefore cannot "pre-fill a weight field" the way
  print time and plate count can — see FR-002a/FR-004a and the revised
  Assumptions below.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a `.3mf` file exported by a supported slicer with complete
  metadata, all three target fields (print time, filament weight, plate
  count) are pre-filled with no manual re-entry required.
- **SC-002**: Makers creating a model from a supported `.3mf` file complete
  the print-time/weight/plate-count portion of model creation with zero
  manual numeric entry, compared to three manual fields today.
- **SC-003**: An unparseable or malformed `.3mf` file never blocks model
  creation — the maker can always still complete the form manually, matching
  today's baseline experience.
- **SC-004**: Values the maker manually edits after an auto-fill are the
  values saved, 100% of the time (no silent overwrite by parsed data).

## Assumptions

- Only Bambu Studio, OrcaSlicer, and PrusaSlicer `.3mf` metadata layouts are
  in scope for parsing; other slicers (e.g. Cura) fall back to thumbnail-only
  extraction per Story 2, matching today's behavior for those files.
- When a `.3mf` file contains multiple plates, pre-filling from the first
  plate only (with accurate total plate count) is an acceptable default;
  full per-plate selection UI is out of scope for this feature.
- Filament *color* and per-color weight breakdown are out of scope for this
  feature — only the aggregate weight needed for the existing single weight
  field is extracted. Richer per-color data is a possible future extension,
  not required here.
- Parsing happens synchronously during the existing upload request/flow (no
  new background job), consistent with how thumbnail extraction works today.
- This feature changes the model *creation* flow (upload-then-create or
  upload-informs-create-form); it does not change the existing secondary
  "attach file to an already-created model" action, which continues to only
  extract the thumbnail as it does today.
- No new persisted fields or migration are required for print time or plate
  count — parsed values map onto the model's existing `print_time_minutes`
  and `prints_per_plate` fields.
- Filament weight has no equivalent plain field to map onto: it is only ever
  recorded as part of a material-usage entry, which also requires choosing
  which specific spool was used and its cost. Automatically matching the
  3MF's filament type/color string to one of the tenant's actual spools is
  explicitly out of scope for this feature (ambiguous/no-match cases would
  need their own resolution UX) — the maker still picks the spool manually;
  only the numeric weight is carried forward as a suggested value for that
  step.
- The parsed weight suggestion must survive from the upload step (during
  model creation) through to the separate material-usage entry step (today,
  on the model detail page, after the model is saved) long enough to
  pre-fill it once — exact mechanism is a planning/implementation decision,
  not a requirement constraint.
