# Quickstart: Validate 3MF Import Auto-Fill

Prerequisites: backend running (`cd backend && poetry run uvicorn app.main:app --reload`),
a valid JWT for a test tenant/user, and at least one real `.3mf` file per
slicer you want to validate (export a sliced plate from Bambu Studio or
OrcaSlicer; PrusaSlicer is expected to frequently fall back — see
[research.md](research.md) §2).

## 1. Parse endpoint in isolation (no model needed)

```bash
curl -X POST http://localhost:8000/api/v1/models/files/parse-3mf \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample-bambu.3mf"
```

Expected: `200` with `print_time_minutes`, `filament_weight_grams`,
`plate_count` populated for a Bambu/OrcaSlicer sliced export — see
[contracts/parse-3mf.md](contracts/parse-3mf.md) for the full response
shape.

## 2. Fallback on malformed/unsupported input

```bash
curl -X POST http://localhost:8000/api/v1/models/files/parse-3mf \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@not-really-a-3mf.txt"
```

Expected: `400` (wrong extension), per FR-009.

```bash
curl -X POST http://localhost:8000/api/v1/models/files/parse-3mf \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@not-really-a-3mf.txt;filename=fake.3mf"
```

Expected: `200` with all metadata fields `null` — a `.3mf`-extensioned file
whose content isn't a real zip degrades gracefully rather than rejecting
(FR-009's extension-only check passes; content-level corruption falls back
to Story 2's all-blank result, matching existing thumbnail-extraction
precedent).

```bash
curl -X POST http://localhost:8000/api/v1/models/files/parse-3mf \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@unsliced-project-export.3mf"
```

Expected: `200`, all metadata fields `null`, `thumbnail_available` reflects
whatever that file actually contains — model creation must still be able
to proceed manually afterward (SC-003).

## 3. End-to-end through the UI

1. Start frontend (`cd frontend && npm run dev`), log in, go to **Models →
   New Model**.
2. Upload a Bambu/OrcaSlicer `.3mf` as the first step of the form.
3. Confirm print time and plate count fields are pre-filled (User Story 1)
   and remain editable (FR-005) — edit one value and confirm the edited
   value, not the parsed one, is what gets saved after create.
4. Save the model, then add a BOM/material line on the model detail page.
   Confirm the weight field is pre-filled with the parsed
   `filament_weight_grams` suggestion, with no spool pre-selected
   (FR-004a).

## 4. Automated test entry points

- Backend unit tests for the new parser: alongside
  `backend/tests/unit/test_model_file_service.py` (existing file covering
  `extract_3mf_thumbnail`/`ModelFileService`) — add cases for
  `parse_3mf_metadata()`: Bambu/Orca happy path, PrusaSlicer best-effort,
  malformed zip, missing metadata, zero/negative sanity values (Edge Cases).
- Backend integration test for the new endpoint: alongside
  `backend/tests/integration/test_model_files_api.py` — success (200),
  auth (401), invalid file (400/422), per the project's standard endpoint
  test matrix.
- Frontend: co-located `ModelForm.test.tsx` additions for pre-fill +
  editability, and a `BOMEditor.test.tsx` addition for the carried-over
  weight suggestion.

Run before committing, per [CLAUDE.md](../../../CLAUDE.md):
```bash
cd backend && poetry run pytest && poetry run ruff check
cd frontend && npm test && npm run lint
```
