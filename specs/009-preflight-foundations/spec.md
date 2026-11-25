# Feature Specification: Preflight foundations — design brief, typed notes, calibrations and print test results

**Feature Branch**: `claude/009-preflight-f85d55` (spec 009)

**Created**: 2026-11-25

**Status**: Draft

**Input**: User description: the "Preflight foundations" block of `specs/backlog.md` (feature 009),
architecture in `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §6:

> Context: a design-check workflow ("Preflight") helps the operator design functional printed
> parts: it records what a part is for (function, loads and their duration, environment,
> neighbouring parts, sales channel), the risks found, the design plan, checks pinned on the part,
> fits calibrated per printer and filament, and results of printed test pieces. Batchivo must store
> all of it so both the operator and AI agents can read and update it.
> 1. Design brief (idea, then model; intended use structured and versioned; risk summary; design
>    plan; design parameters; status of each Preflight step; visible on idea and model pages).
> 2. Typed notes (source, rule reference, severity, optional measured value; existing notes keep
>    working unchanged; filter by source and severity).
> 3. Calibrations (fit value per printer, filament type, orientation and fit type; measured or
>    assumed; from which print and when; superseded, history kept).
> 4. Print test results (print job and model version; outcome; measurements; failure mode; photo;
>    notes).
> 5. Printer connection secrets stored encrypted.
> Constraints: tenant-scoped tables with RLS; calibrations superseded, never edited; no breaking
> change to model file notes; a data migration encrypts existing printer secrets; tests per the
> testing policy.

**Primary client**: the Preflight skill (`~/.claude/skills/preflight`, commands `intent`, `adopt`,
`clarify`, `risk`, `plan`, `design`, `check`, `slice`, `print`, `test`, `learn`, `render`, `ship`,
`quick`). Its "Batchivo mode" reads and writes everything below through the Batchivo API and MCP
server. Every field Preflight writes MUST come back identical when read (no lossy conversion); the
field-by-field correspondence is recorded in `research.md`.

## Clarifications

### Session 2026-11-25

- Q: What does "versioned intent" mean in the design brief? → A: The intent carries its schema version, and every save of the intent, the risk summary or the plan is also kept as a read-only revision (who, when), browsable from the brief.
- Q: How is a Preflight alert ignored with a written justification recorded? → A: A new note status "dismissed" with a mandatory justification, shown on the note, filterable, and reopenable; notes and calls that do not use it are unchanged.
- Q: Must a print test result name both a print job and a model version? → A: At least one of the two; the model version is required for a critical-zone or full-part test, optional for a clearance grid.
- Q: How far can the operator edit the intent on the idea and model pages? → A: Simple fields in a form (function, category, quantity, sales channel, country, success criteria, value statuses); loads, environment and interfaces in a YAML/JSON editor validated by the server. Risk, plan, parameters and step statuses stay editable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep a part's design brief with the idea, then the model (Priority: P1)

The operator (or an AI agent running Preflight) starts a design brief on an idea: what the part is
for (function, loads with their duration, environment, neighbouring parts and how they fit,
quantity, sales channel, success criteria), then the risk summary, the design plan and the design
parameters, and marks each Preflight step as it progresses. When the idea is converted into a
model, the brief is found on the model with nothing retyped. The operator reads it on the idea page
and on the model page.

**Why this priority**: the intended use is the input of every other Preflight step; without a place
to keep it, nothing else in Preflight can work in Batchivo mode.

**Independent Test**: create a brief on an idea with a full Preflight intent document, read it
back identical, convert the idea to a model, and read the same brief from the model.

**Acceptance Scenarios**:

1. **Given** an idea without a brief, **When** the operator or an agent saves an intent document in
   Preflight's format (schema version 1, with `[À PRÉCISER]` placeholders and value statuses
   `déduit` / `estimée` / `validé` / `mesurée`), **Then** the brief is created on the idea and the
   document reads back exactly as written, unknown extra fields included.
2. **Given** an intent document with an invalid enumerated value (for example a load duration that
   is not `permanent`, `cyclic`, `shock` or `short`), **When** it is saved, **Then** it is refused
   with a message naming the field, and nothing changes.
3. **Given** a brief with an intent, **When** the risk summary, the design plan, the design
   parameters or a step status are saved, **Then** each is stored and returned, and each change
   records who made it and when.
4. **Given** an idea with a brief, **When** the idea is converted to a model, **Then** the model page
   shows the same brief and the idea page still shows it, with a link to the model.
5. **Given** a model created directly (no idea), **When** the operator starts a brief on the model,
   **Then** it works the same way as on an idea.
6. **Given** the intent is changed, **When** the operator looks at the brief, **Then** every earlier
   intent, risk summary and plan is kept as a read-only revision (content, who saved it, when),
   listed newest first and viewable from the brief; a revision can never be changed or deleted.
7. **Given** a brief, **When** the operator opens the idea or model page, **Then** a "Design brief"
   panel shows the function, loads, environment, interfaces, success criteria, the risk class and
   summary, the plan, the parameters, and a strip with the status of each Preflight step; open
   placeholders (`[À PRÉCISER]`) and unconfirmed values (`déduit`, `estimée`) are highlighted.

---

### User Story 2 - Typed notes on the part (Priority: P1)

Preflight's geometry check pins each finding on the part as a note at the point measured, with its
source (`preflight`), the rule it comes from (a Preflight rule id such as `dfam.wall.extrusion-multiple`),
a severity (info, warning, failure), the measured value and the expected one. After a test print,
notes from the print result mark where a part broke. Notes written by people keep working exactly as
today. The operator filters the notes on the model page by source and severity.

**Why this priority**: placed, actionable findings are the main thing Preflight brings to the part
itself; it builds on the notes that already exist.

**Independent Test**: create a note without any new field and check it behaves and reads exactly as
before; create a typed note and read its source, rule, severity and values back; filter by source
and severity.

**Acceptance Scenarios**:

1. **Given** the existing note screens and API calls, **When** a note is created without the new
   fields, **Then** it is stored with source "person", no rule, severity "info" and no value, and
   every existing behaviour (resolve, reopen, carry forward to a newer version, archive) is
   unchanged.
2. **Given** a typed note (source `preflight`, rule `dfam.wall.extrusion-multiple`, severity
   failure, measured 0.6 mm, expected 0.9 mm), **When** it is read back, **Then** every field is as
   written.
3. **Given** notes of several sources and severities, **When** the operator or an agent filters by
   source and/or severity, **Then** only matching notes are returned, and filters combine with the
   existing file, version and status filters.
4. **Given** a typed note is carried forward to a newer version, **Then** the new note keeps its
   source, rule, severity and values.
5. **Given** a severity written in Preflight's own words (`info`, `attention`, `échec`), **When** it
   is saved, **Then** it is stored as info, warning and failure respectively and read back in
   Batchivo's words; the correspondence is one-to-one.
6. **Given** a Preflight alert the operator chooses to ignore, **When** they dismiss it with a
   written justification, **Then** the note takes the status "dismissed", keeps the justification,
   who dismissed it and when, and shows them; a dismissal without justification is refused; a
   dismissed note can be reopened (status back to open, the last justification kept in its
   history fields) and is not carried forward to newer versions.
7. **Given** the model page, **Then** each typed note shows its severity (colour and label), its
   source and its rule id, and the measured and expected values when present.

---

### User Story 3 - Fits calibrated per printer and filament (Priority: P2)

After printing a clearance grid, Preflight's `learn` step records, for a printer, a material (and
optionally a specific filament), a print orientation and a fit type (slide, press, snap,
print-in-place), the clearance per side that works, how it was obtained (measured, or assumed until
a measurement exists), the print it came from and when. A new value for the same combination
supersedes the previous one; nothing is edited or deleted, so the history shows how the fit evolved.
Preflight's `plan` step asks Batchivo for the current value of a combination before falling back to
its generic rule.

**Why this priority**: the workshop's own measurements replacing generic values is what makes the
second part need fewer prints than the first; it needs printers and prints, which exist already.

**Independent Test**: record a fit value, record a second one for the same combination, and check
that the lookup returns the second, the history returns both in order, and the first cannot be
changed.

**Acceptance Scenarios**:

1. **Given** no calibration for (printer P, PLA, vertical, slide), **When** the lookup is asked,
   **Then** it answers that none exists, so the caller falls back to its rule.
2. **Given** a measured value of 0.20 mm recorded from print job J, **When** the lookup is asked,
   **Then** it returns 0.20 mm, provenance measured, the print it came from and the date.
3. **Given** that value, **When** 0.15 mm is recorded for the same combination, **Then** the lookup
   returns 0.15 mm, the 0.20 mm record is marked as superseded by the new one, and the history lists
   both, newest first.
4. **Given** any calibration record, **When** someone tries to change or delete its value, **Then**
   the request is refused.
5. **Given** a value recorded for a specific filament (brand and colour) and another for the
   material only, **When** the lookup asks with that filament, **Then** the filament-specific value
   wins; asked with only the material, the material-level value is returned.
6. **Given** the printers page, **When** the operator opens a printer's calibrations, **Then** the
   current value of each combination is listed with its provenance, source print and date, and the
   superseded values are shown in its history; the operator can record a new value by hand.

---

### User Story 4 - Results of printed test pieces (Priority: P2)

When a test piece (a critical-zone section, a clearance grid, or the full part) has been printed,
the operator or Preflight records the result: pass, fail or partial, the measurements taken, the
failure mode if any, a photo and free notes. The result is linked to the print job and the model
version it tested, so the model page shows which version passed its tests, and Preflight's `ship`
step can check that a load-bearing part has a passing test.

**Why this priority**: it closes the loop (print → learn → plan), but the brief and notes are useful
without it.

**Independent Test**: record a failed result with measurements and a photo against a print job and
a model version, read it back, and list the results of the model.

**Acceptance Scenarios**:

1. **Given** a finished print job of a model version, **When** a result is recorded (outcome fail,
   failure mode "broke at the root of the hook at 7 kg", measurements, a photo, notes), **Then** it
   reads back identical and appears on the model page and in the list of results of that version.
2. **Given** a result recorded against a print job of another shop, or a version of another model,
   **Then** it is refused as not found.
3. **Given** an outcome other than pass, fail or partial, **Then** it is refused.
4. **Given** the test results of a model, **When** the operator filters by version or outcome,
   **Then** only matching results are listed, newest first.
5. **Given** a clearance grid printed by hand outside Batchivo, **When** its result is recorded with
   a model version or a print job but not both, **Then** it is accepted; **Given** a result with
   neither, **Then** it is refused; **Given** a critical-zone or full-part result without a model
   version, **Then** it is refused with a message saying the version is required.

---

### User Story 5 - Printer secrets encrypted at rest (Priority: P1)

The printer's LAN access code and cloud token are stored encrypted. Existing printers keep working
after the upgrade: a data migration encrypts the values already stored, and every part of Batchivo
that uses them (connection, status, sending a print) still gets the clear value when it needs it.
Responses keep masking them as today.

**Why this priority**: these secrets give control of a physical machine; spec 011 now uses them to
send prints, so they must not sit in clear in the database.

**Independent Test**: store an access code, check the stored value is not the clear text and the
connection still receives the clear value; run the migration over a clear value and check it is
encrypted and still usable; run its downgrade and check it is clear again.

**Acceptance Scenarios**:

1. **Given** a printer connection is created or updated with an access code or cloud token, **Then**
   the stored value is encrypted and the API response shows it masked exactly as before.
2. **Given** a connection saved before the upgrade with a clear access code, **When** the migration
   runs, **Then** the stored value becomes encrypted, running it again changes nothing, and the
   printer connects and receives prints as before.
3. **Given** a stored secret that can no longer be decrypted (the server key changed), **When** the
   printer is used, **Then** the operation says the access code must be entered again, no secret or
   ciphertext appears in the message or logs, and other printers are unaffected.
4. **Given** the migration is rolled back, **Then** the values are clear again and usable by the
   previous release.

---

### User Story 6 - AI agents use all of this through the MCP server (Priority: P2)

An AI agent running Preflight with a personal API token reads and writes briefs, typed notes,
calibrations and test results through the Batchivo MCP server, with the same checks as the API:
reading needs the `read` scope, writing needs `write`.

**Why this priority**: Preflight is an agent; without tools it can only use the screens.

**Independent Test**: with a read token, list the preflight tools and read a brief; check write
tools are absent; with a write token, save an intent and record a calibration and a test result.

**Acceptance Scenarios**:

1. **Given** a token with `read`, **When** the agent lists tools, **Then** it sees the brief,
   calibration and test-result read tools and no write tools.
2. **Given** a token with `write`, **When** the agent saves an intent document, a step status, a
   calibration, a test result or a typed note, **Then** the data is stored and the result returned
   as JSON.
3. **Given** the agent asks the calibration lookup for a combination, **Then** it gets the same
   answer as the API (current value with provenance, or none).
4. **Given** an API error (not found, validation), **Then** the agent receives the error message.

### Edge Cases

- A brief exists on an idea and someone starts another brief on the model converted from it: the
  existing brief is used; there is at most one brief per idea and per model.
- An idea with a brief is converted to a product with its model: the brief follows to the model.
- An idea is archived or a model is deleted (models are deactivated, not erased): the brief stays
  attached and readable.
- An intent document much larger than any real one (over 256 KB) or a plan/risk text over 100 000
  characters is refused.
- A step status for a step Preflight does not have is refused.
- A calibration for a printer of another shop, or with a clearance below 0 or above 2 mm, is refused.
- Two calibrations for the same combination recorded at the same moment: one supersedes the other;
  there is never more than one current value per combination.
- The printer behind a calibration is deleted: its calibrations go with it.
- A test result's photo is not an image or exceeds the image size limit: refused, nothing stored.
- A print job deleted later: its test results remain, without the link.
- A connection has an empty access code: nothing is encrypted, it stays empty.
- A typed note with a measured value but no unit: accepted (the unit is optional), shown without
  a unit.

## Requirements *(mandatory)*

### Functional Requirements

**Design brief**

- **FR-001**: The system MUST let a member of a shop create one design brief on an idea or on a
  model, and read, update it; at most one brief per idea and per model.
- **FR-002**: The brief MUST hold the intent document in Preflight's intent format (schema version
  1: slug, function, category, images, loads, environment, interfaces, quantity, selling, sales
  channel, country, EU, third-party model and licence, alternatives, success criteria), stored
  exactly as written, including the `[À PRÉCISER]` placeholder, value statuses and any extra field.
- **FR-003**: Saving an intent MUST validate the schema version and the enumerated values Preflight
  itself validates (load duration, load unit, interface fit, value status, sales channel) and
  refuse an invalid document with the field named; placeholders are always accepted.
- **FR-004**: The brief MUST hold the risk summary (text, plus the risk class `faible`, `moyen`,
  `élevé` or `arrêt` and, optionally, the structured triage result Preflight computes), the design
  plan (text), and the design parameters (named values with unit and provenance, as Preflight's
  parameter file).
- **FR-005**: The brief MUST hold a status for each per-part Preflight step — intent, adopt,
  clarify, risk, plan, design, check, slice, print, test, learn, render, ship, quick — among
  `not_started`, `in_progress`, `done`, `skipped` and `blocked`, each with the date it was last set.
- **FR-006**: When an idea with a brief becomes a model (conversion to a model or to a product), the
  brief MUST be reachable from that model and still from the idea, without copying.
- **FR-007**: Every change to a brief MUST record who made it and when. Every save that changes the
  intent, the risk summary (text, class, triage result) or the plan MUST also append a read-only
  revision of that part (its full content, schema version for the intent, author, date); revisions
  are listed per brief, newest first, filterable by part, and never edited or deleted. Parameters
  and step statuses keep only their last value and date.
- **FR-008**: The idea and model pages MUST show the brief as described in User Story 1 scenario 7,
  and let the operator start a brief, set step statuses and edit the risk summary, plan and
  parameters. The intent is shown in a readable form; the operator edits its simple fields
  (function, category, quantity, selling, sales channel, country, success criteria, and the status
  of each value) in a form, and its loads, environment and interfaces in a YAML/JSON editor; both
  go through the same server validation as an agent's save, and an invalid edit is refused with the
  field named and nothing lost from the editor.

**Typed notes**

- **FR-009**: Notes pinned on model files MUST gain an optional source (`person`, `preflight`,
  `print`; default `person`), rule reference (free text up to 100 characters, a Preflight rule id
  such as `fit.slide.clearance` or `reg.eu.gpsr`), severity (`info`, `warning`, `failure`; default
  `info`), measured value, expected value and unit.
- **FR-010**: Every existing note request and response MUST keep working unchanged; existing notes
  read as source `person`, severity `info`.
- **FR-011**: Note lists MUST be filterable by source and by severity, alone or together, and with
  the existing filters.
- **FR-012**: Preflight's severity words `attention` and `échec` MUST be accepted as `warning` and
  `failure`.
- **FR-013**: Carrying a note forward MUST copy its type fields.
- **FR-013a**: A note MAY be set to the new status `dismissed` only with a justification (1 to 2000
  characters); the justification, who dismissed it and when are stored and returned; a dismissed
  note can be reopened; it is counted with neither open nor resolved notes; the status filter
  accepts `dismissed`. Existing statuses and their rules are unchanged.
- **FR-014**: The model page MUST show each note's severity, source, rule and values, and offer
  source and severity filters.

**Calibrations**

- **FR-015**: The system MUST record a calibration: printer, material type (required), filament type
  (optional, refines the material), orientation (`vertical` or `horizontal`), fit type (`slide`,
  `press`, `snap`, `print-in-place`), clearance per side in mm (0 to 2, up to 3 decimals, exact),
  provenance (`measured` or `assumed`), source print job (optional), date measured, notes, and who
  recorded it.
- **FR-016**: Recording a calibration for a combination that already has a current value MUST mark
  the previous one as superseded by the new one, atomically; a calibration's value and its fields
  MUST never be edited or deleted through the application.
- **FR-017**: A lookup MUST return the current calibration for printer, fit type, orientation and
  material, preferring a filament-specific value when a filament is given, or say that none exists.
- **FR-018**: A history listing MUST return all calibrations of a printer (optionally filtered by
  combination), current and superseded, newest first.
- **FR-019**: The printers page MUST show each printer's current calibrations and their history, and
  let the operator record a new value.

**Print test results**

- **FR-020**: The system MUST record a test result with an outcome (`pass`, `fail`, `partial`), a
  print job and/or a model file version (at least one; the version is required for the kinds
  critical zone and full part), measurements (named values with
  unit, as Preflight writes them), a failure mode (text), one photo, notes, a test kind (clearance
  grid, critical zone, full part) and who recorded it.
- **FR-021**: Test results MUST be listed per model (filter by version and outcome) and per print
  job, newest first, and shown on the model page.
- **FR-022**: A test result MAY be corrected (outcome, measurements, notes) by a member; each change
  records who and when.

**Printer secrets**

- **FR-023**: Printer connection access codes and cloud tokens MUST be stored encrypted with the
  application's existing credential encryption, and decrypted only where a printer operation needs
  them.
- **FR-024**: A data migration MUST encrypt existing clear values, be safe to run twice, and decrypt
  them on downgrade.
- **FR-025**: A secret that cannot be decrypted MUST make the printer operation fail with an
  actionable message ("enter the access code again"), without exposing the secret or its encrypted
  form.
- **FR-026**: Responses MUST keep masking secrets as before (last four characters of the clear
  access code; the cloud token fully masked).

**Agents, access and isolation**

- **FR-027**: All new data MUST belong to one shop, be invisible to other shops at the database
  level, and be reachable only by signed-in users of that shop; viewers read, members and above
  write.
- **FR-028**: Every new read endpoint MUST accept personal API tokens with the `read` scope and
  every new write endpoint the `write` scope; deleting a brief stays JWT-only.
- **FR-029**: The MCP server MUST offer tools to read and write briefs (intent, risk, plan,
  parameters, step status), to add and filter typed notes, to look up, record and list calibrations,
  and to record and list test results.

### Key Entities

- **Design brief**: one per idea and/or model of a shop; intent document (Preflight format), risk
  class, risk summary, triage result, plan, parameters, step statuses with dates; who changed it and
  when.
- **Design brief revision**: an immutable copy of the intent, the risk summary or the plan as saved
  at one moment, with its author and date.
- **Model file note (extended)**: existing pinned note plus source, rule reference, severity,
  measured value, expected value, unit, and a dismissal (justification, who, when) for the new
  `dismissed` status.
- **Calibration**: printer × material type (× optional filament type) × orientation × fit type →
  clearance per side, provenance, source print job, date measured, superseded-by link; immutable.
- **Print test result**: outcome, kind, print job, model file version, measurements, failure mode,
  photo, notes, author.
- **Printer connection (changed)**: access code and cloud token encrypted at rest.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An intent document taken from Preflight's template, with every field filled or left as
  a placeholder, reads back byte-for-byte equivalent (same keys, same values) in 100% of the
  round-trip tests, through both the API and the MCP tools.
- **SC-002**: 100% of the existing note tests pass unchanged after the change.
- **SC-003**: For any combination, the calibration lookup returns the most recent value and the
  history keeps 100% of the values ever recorded.
- **SC-004**: After the migration, no printer connection stores a clear access code or cloud token,
  and every printer that connected before connects after.
- **SC-005**: The operator sees a part's brief, its open failures and its last test outcome on the
  model page without leaving it.
- **SC-006**: An agent with a write token completes "save intent → set risk → pin a typed note →
  record a calibration → record a test result" using only MCP tools.

## Assumptions

- The Preflight skill is not changed by this feature; where it must change to talk to Batchivo
  (for example to call the calibration lookup instead of reading `calibration.yaml`), the change is
  described in `plan.md` and reported to the orchestrator.
- The workshop profile parts that Batchivo does not store today (country, seller status, CAD
  licence, safety policy) stay in Preflight's local `atelier.yaml`; storing them is out of scope.
- Intent images stay where they already live (idea timeline entries, model images); the brief only
  keeps Preflight's references to them.
- Material type is the shop-independent material list (PLA, PETG…); filament type is the shop's
  brand-and-colour filament.
- Role rules are those of model file notes: viewers read, members and above write.
- Generic rule values (the `kb/` files) stay in Preflight; Batchivo stores rule ids, never rule
  contents.
- The existing credential encryption (key derived from the server secret) is reused; changing the
  server secret makes stored secrets unreadable, as for other stored credentials today.
