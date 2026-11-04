# Research: Model File Versions, Measurable Source File, 3D Viewer and Pinned Notes

## D1 — How a version is stored

- **Decision**: a new `model_file_versions` table (label, note, sequence, is_active, print_file_id,
  created_by). `model_files` gains `version_id` (FK, NOT NULL after backfill). The existing
  free-text `model_files.version` column is kept and written with the version's label so current
  clients reading it still see something meaningful. `is_primary` is left as-is (per file type)
  and no longer drives anything new.
- **Rationale**: "one active version per model" and "one print file per version" become a partial
  unique index and a FK. The spec's assumption (a version groups a sliced file with its source)
  needs a grouping row.
- **Alternatives**: `is_primary` as "active" — rejected, it is unique per model *and file type*,
  so a model could have an active STL and an active G-code from different versions. A version
  label string only — rejected, no place for note/active/print file without repeating on every row.

## D2 — Backfill of existing files (FR-016, SC-004)

- **Decision**: in the migration, for each model with at least one file create version
  sequence 1, label `"1"`, active, created_by = NULL; attach all its files; `print_file_id` =
  the primary sliced file, else the newest sliced file, else NULL. `is_sliced` is backfilled from
  the name and file type only (`.gcode`, `.gcode.3mf`, file type `gcode`): a migration does not
  read stored content, so a sliced plate uploaded under a plain `.3mf` name stays `false` until it
  is re-uploaded (as built; uploads after the migration inspect the content). No model, printer-config,
  material or dimension column is written.
- **Rationale**: nothing the engine reads changes, so every cost is identical; the SC-004 test
  compares `calculate_model_cost` per model before and after the migration.
- **Alternatives**: one version per distinct `version` string — rejected, those strings are free
  text and often empty; grouping by them would invent a history that never existed.

## D3 — Detecting a sliced file (`is_sliced`)

- **Decision**: at upload, `is_sliced = true` when the name ends in `.gcode`, or the file is a zip
  (3MF) containing `Metadata/plate_<n>.gcode`. Stored once; file content is immutable.
- **Rationale**: the plain-language "no geometry" message (FR-004) and the print-file choice
  (FR-011a) both need it, and recomputing it means re-reading the file.

## D4 — Print figures and the activation review (FR-012, FR-012a)

- **Decision**: `ModelFileVersionService.activation_preview(version_id)` reads the version's print
  file content and runs the existing `parse_3mf_metadata` (print time, plate count, filament
  weight) — plain `.gcode` reads the slicer header lines when present, otherwise reports "not
  available". Dimensions come from the version's newest file with `measurement_status = done`.
  The preview returns `{field, current, proposed, target}` rows where `target` is:
  - `model_printer_config` for the planned printer when a config row exists (that is what
    `costing.py` reads first), else `model`, for `print_time_minutes` and `prints_per_plate`;
  - the model's single `model_material` row for `weight_grams` when exactly one exists; with
    several materials the weight row is informational and not selectable;
  - `dimensions` for length/width/height, applied through `item_dimensions` adoption.
  `activate(version_id, apply=[fields])` flips the active flag and writes only the selected
  fields through the existing writers (`ModelPrinterConfigService`, model update path with
  `record_operator_write`, dimension adoption), in one transaction. Current values are re-read at
  apply time (edge case: concurrent edits).
- **Rationale**: one implementation per figure (constitution III); provenance becomes `measured`
  with the user, like any operator write (constitution VI).
- **Alternatives**: auto-apply on activation — rejected by FR-012 and clarification Q3.

## D5 — Viewer libraries

- **Decision**: `three` (^0.180), `@react-three/fiber` (^9, React 19), `@react-three/drei` (^10:
  `OrbitControls`, `Html` for tooltips, `Bounds`), `fflate` (^0.8) for unzipping in the worker.
  Meshes: three's `STLLoader` and `3MFLoader` (`three/examples/jsm`). G-code: a small in-house
  parser (`lib/viewer/gcode.ts`) handling G0/G1/G2/G3 (arcs flattened), G90/G91, M82/M83,
  `;LAYER_CHANGE` / `; CHANGE_LAYER` / Z changes, and the Bambu/Orca header (`; printer_model`,
  `; filament_type`, `; nozzle_diameter`) — output is per-layer `Float32Array` segment buffers
  rendered as `LineSegments` with `drawRange` for the slider. Exact versions are pinned when
  installed (`npm install` writes them to the lockfile).
- **Rationale**: gcode-preview drives its own renderer and canvas, which fights react-three-fiber
  and cannot run in a worker; an own parser is ~300 lines, unit-testable, and shares the canvas,
  bed outline and pin raycasting with the mesh view.
- **Alternatives**: gcode-preview (rejected above); JSZip (heavier, slower than fflate in workers).

## D6 — Large files (FR-022, SC-005)

- **Decision**: the file is fetched through the existing download endpoint as an `ArrayBuffer` and
  transferred to `modelParse.worker.ts`. Full preview up to 50 MB of file. Above it, the worker
  keeps extrusion moves only and samples every Nth segment so the total stays under 2 million
  segments; for meshes above it, it keeps every Nth triangle under 1.5 million. The result carries
  `reduced: true` and the viewer shows "Reduced preview: large file".
- **Rationale**: parsing off the main thread keeps the page responsive; the caps keep GPU memory
  bounded on phones.

## D7 — Notes coordinates and carry-forward (FR-026, FR-029, FR-029a)

- **Decision**: positions and normals are stored in the file's own coordinate space (mm), as
  six `double precision` columns plus a nullable `layer`. A pin is placed by raycasting the mesh,
  or, on G-code, the clicked point on the current layer's segments (layer recorded). Carry forward
  creates a new note on the target file with `carried_from_note_id`, copying text and position;
  the original gets `status = carried_forward`, `carried_to_version_id`. Ghost pins = open notes of
  any earlier version of the same model.
- **Rationale**: clarification Q2; geometry is not money, so floating point is appropriate here.

## D8 — Tenant session and roles

- **Decision**: new routers use `get_tenant_db`; the existing `model_files` router switches from
  `get_db` to `get_tenant_db` in this change (constitution I). Writes require `RequireMember`;
  reads require an authenticated tenant user (viewers can read, FR-032).
- **Rationale**: RLS engages only through `get_tenant_db`.

## D9 — Delete rules (FR-015, FR-030)

- **Decision**: `DELETE /models/{id}/files/{fid}` returns 409 when the file is the last file of the
  active version, or is the active version's print file while the version holds another sliced
  file (operator must mark another print file first). Deleting the print file of an inactive
  version reassigns its print file to its newest remaining sliced file. Notes on a deleted file get
  `archived_at` and `model_file_id = NULL` (FK `ON DELETE SET NULL`), keeping `version_id`.

## D10 — Keeping the file from the auto-fill step (FR-005)

- **Decision**: the create flow already uploads the parsed `.3mf` after creation; it becomes an
  explicit "Keep this file on the model" checkbox (default on) on both create and edit, uploaded
  into the model's active version (or version 1 for a new model). The source-file picker on both
  screens uploads `.stl`/`.3mf` the same way.

## D11 — No-geometry message (FR-004)

- **Decision**: `mesh_bounds` raises with a reason code (`no_geometry`) stored as
  `measurement_status = failed` plus `measurement_reason = "no_geometry"`; the API exposes the
  reason, and `FileMeasurementSummary` maps it (with `is_sliced`) to: "This is a sliced plate. It
  holds the print, not the part's shape, so it can't be measured. Upload the project .3mf (Bambu
  Studio: File → Save project) or the .stl."
