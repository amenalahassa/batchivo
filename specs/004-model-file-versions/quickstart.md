# Quickstart: validating model file versions, the viewer and notes

## Prerequisites

- Local stack running (`dev.ps1`, or backend `poetry run uvicorn app.main:app --reload` and
  frontend `npm run dev`), migrated to head: `cd backend && poetry run alembic upgrade head`.
- A tenant with one printer whose bed size is set (A1: 256 × 256 × 256 mm).
- Test files: a small `.stl`, a Bambu Studio project `.3mf` (File → Save project), and a sliced
  `.gcode.3mf` with two plates (File → Export plate sliced file / Export all sliced files).

## Automated checks

```bash
cd backend && poetry run pytest tests/integration/test_model_files_api_versions.py tests/integration/test_model_file_versions_api.py tests/integration/test_model_file_notes_api.py tests/integration/test_version_switch_history.py tests/integration/test_migration_model_file_versions.py tests/unit/test_model_file_version_model.py tests/unit/test_mesh_bounds_reasons.py tests/unit/test_gcode_metadata.py
```

```bash
cd frontend && npm test -- src/lib/viewer src/components/viewer src/components/models
```

```bash
cd frontend && npx playwright test --project=pricing e2e/pricing/file-versions.spec.ts
```

## Manual scenarios

1. **Source file on create (US1)** — New model → attach the `.stl` → save. Expect: the file is
   listed under version "1" (active) and the model shows measured dimensions labelled
   "measured from <file>".
2. **No geometry (US1, FR-004)** — On that model, upload the `.gcode.3mf`. Expect: the file is kept
   and its row reads "This is a sliced plate… Upload the project .3mf or the .stl", not the bare
   parser error.
3. **Entered dimensions win (FR-003)** — Enter dimensions by hand, upload the project `.3mf`.
   Expect: dimensions unchanged, the measurement offered for adoption.
4. **New version stays inactive (Q3, FR-009a)** — Upload the `.gcode.3mf` as a new version "2"
   with note "thicker walls". Expect: version 2 listed first, not active, a "Make active" prompt.
5. **Activation review (US2, FR-012)** — Click "Make active". Expect: rows for print time, parts
   per plate, weight, dimensions with old → new values; apply only print time. Expect: only print
   time changed on the cost profile, its badge "Measured" today; version 2 active.
6. **Print file switch (FR-011a, FR-012a)** — Add a second sliced file to version 2, mark it as
   print file. Expect: the same review dialog, figures from the new file.
7. **History untouched (FR-014)** — An order costed before step 5 shows the same figures.
8. **Delete rules (FR-015)** — Try deleting the active version's print file while another sliced
   file exists → refused ("mark another print file first"); delete the last file of the active
   version → refused ("make another version active first").
9. **Viewer (US3)** — Open the `.stl` (solid, rotate/zoom), the `.gcode.3mf` (toolpaths, layer
   slider, plate picker), check the 256 mm bed outline. Open a G-code sliced for another printer:
   a notice names the difference. Open a > 50 MB G-code: "Reduced preview" and the page scrolls
   while it loads.
10. **Notes (US4)** — On version 1 pin two notes; open version 2: two faded pins. Resolve one,
    carry the other forward, then "Move" the carried pin and click the new surface. Expect: version 1 lists
    one "resolved in 2" and one "carried forward to 2"; version 2 lists one open note.
11. **Phone** — At 375 px wide, the notes list is readable and filterable without the 3D view.
12. **Viewer role** — As a viewer, files open and notes read, but upload, activate and note
    buttons are absent and the API returns 403.
13. **Bundle (SC-007)** — `npm run build && node scripts/check-viewer-chunk.mjs`: the three.js
    code is only in the viewer chunk, not in the main entry chunk.
