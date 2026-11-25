# Feature Specification: Model File Versions, Measurable Source File, 3D Viewer and Pinned Notes

**Feature Branch**: `004-model-file-versions`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "Model file versions, a measurable source file, a 3D viewer and pinned notes. A Bambu Studio sliced export (.gcode.3mf) holds G-code but no mesh, so measuring it fails with 'The 3MF build has no geometry' and the model gets no dimensions for the packaging advisor and postage. Operators revise their designs and want to keep every version, mark one active for the final print, view any file in 3D, and pin notes on the part that carry from one version to the next." (full prompt in `specs/backlog.md`)

## Clarifications

### Session 2026-11-03

- Q: When the active version holds several sliced files, which one feeds print time, plate count and filament weight to the cost profile? → A: The operator marks one sliced file per version as its print file; only that file feeds the cost profile.
- Q: When an open note from version 1 is carried forward to version 2, is it the same note or a new one? → A: A new note is created on version 2, linked to the original; the original becomes "carried forward to version 2" and keeps its position; the new note can be repositioned on the reshaped part.
- Q: Does a newly uploaded version become active automatically? → A: No. A new version stays inactive and the app offers "Make active" (with the figure review) right after the upload; only a model's first version becomes active on its own.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Attach a measurable source file to a model (Priority: P1)

An operator creating or editing a model attaches the design's source file — an
.stl, or the project .3mf saved from the slicer — alongside or instead of the
sliced plate. The file is kept with the model and measured, and the measured
size is offered as the model's dimensions. When the operator picks a sliced
export (.gcode.3mf or .gcode) for measuring, the screen says in plain words that
a sliced plate carries no shape to measure and names what to upload instead.

**Why this priority**: Without dimensions the packaging advisor and postage
cannot work for the model, and today the most common file an operator has to
hand (the sliced plate) cannot provide them. This alone unblocks packaging for
every model.

**Independent Test**: Create a model, attach an .stl on the create screen, save,
and confirm the model shows measured dimensions offered for adoption; attach a
.gcode.3mf and confirm the plain-language message naming the project .3mf or .stl.

**Acceptance Scenarios**:

1. **Given** the create-model screen, **When** the operator attaches an .stl and saves, **Then** the file is listed on the model and its measured length, width and height are offered as the model's dimensions.
2. **Given** a model with no dimensions, **When** a measurable source file is attached, **Then** the measured dimensions are applied and labelled as measured from that file.
3. **Given** a model whose dimensions the operator entered, **When** a measurable file is attached, **Then** the entered dimensions are kept and the measurement is offered for adoption, never applied on its own.
4. **Given** the operator attaches a .gcode.3mf, **When** it is checked for geometry, **Then** the screen explains that a sliced plate has no shape to measure and suggests "Save project" (.3mf) or the .stl, and the file itself is still kept.
5. **Given** the "Auto-fill from .3mf" step on the create or edit screen, **When** the operator parses a file there, **Then** they can choose to keep that file on the model as well as applying its print time, plate count and filament weight.

---

### User Story 2 - Keep versions and choose the active one (Priority: P1)

An operator revising a design uploads the new files as a new version, with a
short note on what changed ("thicker walls", "fixed overhang on the handle").
Earlier versions stay listed, newest first. The operator marks one version as
active — the one used for the final print. Making a different version active
shows which cost-profile and dimension figures would change, and the operator
chooses which to apply.

**Why this priority**: Operators iterate on designs constantly; losing the
earlier file or not knowing which file is the production one leads to printing
the wrong version and to costs computed from a file nobody prints.

**Independent Test**: Upload version 1 and version 2 files with notes, make
version 2 active, review the proposed figure changes, apply some, and confirm
version 1 is still listed and can be downloaded or made active again.

**Acceptance Scenarios**:

1. **Given** a model with files, **When** the operator uploads a file, **Then** they can place it in a new version (with a label and a note) or add it to an existing version; a new version is created inactive and the app offers "Make active".
2. **Given** a model with several versions, **When** the operator views its files, **Then** versions are listed newest first, each showing its label, note, upload date, uploader and files, with the active version clearly marked.
3. **Given** version 1 is active, **When** the operator makes version 2 active, **Then** they see each print time, plate count, filament weight (from version 2's print file) and dimension that would change, from old to new value, and only the figures they select are applied.4. **Given** version 2 is active, **When** the operator opens a past order or production run costed while version 1 was active, **Then** its recorded figures are unchanged.
5. **Given** a file of the active version, **When** the operator tries to delete the last file of that version, **Then** the deletion is refused with a message asking them to make another version active first.
6. **Given** a version that holds only a sliced file, **When** it is active, **Then** dimensions come from the newest measurable file of the same version, and when none exists the model says it has no measurable file for the active version.
7. **Given** a version with two sliced files, **When** the operator marks the second as the print file, **Then** only that file's print figures are proposed for the cost profile, and the first file stays in the version unused for costing.

---

### User Story 3 - Check a file in a 3D viewer (Priority: P2)

From the model's file list the operator opens any file in a 3D viewer inside the
app. A source file shows as a solid part; a sliced file shows its toolpaths with
a layer slider. The planned printer's bed outline is drawn so a part that is off
the bed or too large is obvious, and when the sliced file was prepared for a
different printer, filament or nozzle than the model's planned machine, the
viewer says so.

**Why this priority**: It lets the operator confirm they uploaded the right file
and that it fits the machine without opening the slicer, but the feature still
delivers value without it.

**Independent Test**: Open an .stl and a multi-plate .gcode.3mf in the viewer;
rotate the part, step through layers, switch plates, and check the bed outline
and the "sliced for a different printer" notice.

**Acceptance Scenarios**:

1. **Given** an .stl or project .3mf, **When** the operator opens it, **Then** the part is shown as a solid that can be rotated, zoomed and panned.
2. **Given** a .gcode or .gcode.3mf, **When** the operator opens it, **Then** its toolpaths are shown with a slider that limits the view to layers up to the one chosen.
3. **Given** a .gcode.3mf holding several plates, **When** it is opened, **Then** the operator can choose which plate to view.
4. **Given** a model planned on a printer with a known bed size, **When** any file is viewed, **Then** the bed outline is drawn, and a part extending beyond it is visibly outside the outline.
5. **Given** a sliced file whose header names a printer, filament or nozzle that differs from the model's planned machine, **When** it is viewed, **Then** the difference is stated next to the viewer.
6. **Given** a file above the full-preview size limit, **When** it is opened, **Then** a reduced preview is shown with a note saying so, and the page stays responsive.
7. **Given** a file recorded as a local reference (not uploaded), **When** the operator tries to view it, **Then** the app explains it can only view uploaded files.

---

### User Story 4 - Pin notes on the part and carry them to the next version (Priority: P3)

In the viewer the operator clicks a point on the part — or a layer of the
toolpaths — and leaves a note there. Notes show as numbered pins whose tooltips
stay attached to their point as the view turns, and are also listed beside the
viewer. When a newer version is opened, the previous version's open notes appear
as faded pins at the same place, and the operator marks each one resolved in
this version or carries it forward.

**Why this priority**: It turns the version history into a record of what was
wrong and what was fixed, which is valuable but depends on stories 2 and 3.

**Independent Test**: Pin two notes on version 1, open version 2, mark one
resolved and carry the other forward, then confirm version 1 shows one note
"resolved in version 2" and version 2 shows the carried note as open.

**Acceptance Scenarios**:

1. **Given** a file open in the viewer, **When** the operator clicks a point on the part and writes a note, **Then** a numbered pin appears there and the note is listed beside the viewer with its author and date.
2. **Given** a sliced file open at a given layer, **When** the operator places a note, **Then** the note records that layer and shows it in the list.
3. **Given** pinned notes, **When** the view is rotated or zoomed, **Then** each pin stays on its point and its tooltip follows it.
4. **Given** version 1 has open notes, **When** the operator opens a file of version 2, **Then** those notes appear as faded pins at the same coordinates, each offering "resolved in this version" and "carry forward".
5. **Given** the notes list, **When** the operator filters it by open or resolved, **Then** only matching notes are shown, and the list is readable without the 3D view (e.g. on a phone).
6. **Given** a file with open notes, **When** that file is deleted, **Then** its notes are archived and remain visible in the model's note history, never silently dropped.

---

### Edge Cases

- A project .3mf that contains several objects: the measurement reports the overall plate size and says the objects are measured as laid out, as today.
- A file whose upload succeeds but whose measurement fails for another reason (corrupt, unsupported unit): the file is kept and the reason is shown; the model's dimensions are untouched.
- Two files of the same version are both measurable: the newest one gives the dimensions, and the screen names which file was used.
- The active version is changed while another operator is editing the cost profile: the change-review step shows the figures as they are at the moment of applying, not as they were when the review opened.
- Existing models: all their current files become version "1", and the version holding the current primary file is active, so nothing a model costs today changes on migration.
- A note placed on version 1 points at a spot that no longer exists on version 2 (the part was reshaped): the faded pin is still shown at the old coordinates, labelled as from the earlier version, so the operator can still resolve or carry it; a carried note starts at the old position and can be moved onto the new surface.
- A model with no planned printer: the viewer shows no bed outline and says the model has no planned machine.
- A .gcode.3mf with no plate G-code inside (a project mistakenly named .gcode.3mf): the viewer falls back to showing the mesh if there is one, or explains that nothing viewable was found.
- A viewer-only user (viewer role): can open files and read notes, but cannot upload, change the active version or add notes.

## Requirements *(mandatory)*

### Functional Requirements

**Source file and measurement**

- **FR-001**: The create-model and edit-model screens MUST let the operator attach one or more files (.stl, .3mf, .gcode, .gcode.3mf) that are stored with the model.
- **FR-002**: The system MUST measure every attached file that contains a mesh and offer the result as the model's dimensions.
- **FR-003**: A measurement MUST be applied automatically only when the model has no dimensions; otherwise it MUST be offered for adoption and MUST NOT replace operator-entered dimensions.
- **FR-004**: When a file contains no geometry, the system MUST keep the file and show a plain-language explanation naming the files that can be measured (the slicer's saved project .3mf, or the .stl).
- **FR-005**: The "Auto-fill from .3mf" step MUST offer to keep the parsed file on the model in addition to applying the parsed print time, plate count and filament weight.
- **FR-006**: Dimensions applied from a file MUST record their provenance as measured, the file they came from and when.

**Versions and the active version**

- **FR-007**: Every model file MUST belong to exactly one version of its model; a version MUST have a label and MAY have a note on what changed.
- **FR-008**: A version MUST be able to hold several files, sliced and unsliced alike.
- **FR-009**: Exactly one version per model MUST be active once the model has any file. A model's first version MUST become active on its own; any later version MUST stay inactive until the operator makes it active.
- **FR-009a**: Right after a new version is uploaded, the system MUST offer to make it active, leading to the figure review of FR-012; declining leaves the current active version and all figures unchanged.
- **FR-010**: The file list MUST show versions newest first, each with its label, note, upload date, uploader, files and whether it is active.
- **FR-011**: Any version MUST be downloadable file by file and MUST be able to be made active again.
- **FR-011a**: A version holding sliced files MUST have exactly one of them marked by the operator as its print file; a version's first sliced file becomes its print file until the operator marks another.
- **FR-012**: Making a version active MUST present every print-time, plate-count, filament-weight and dimension figure that differs between the current values and that version's print file (for print figures) and measurable file (for dimensions), and MUST apply only the figures the operator selects.
- **FR-012a**: Marking a different print file within the active version MUST go through the same review of changed figures as FR-012.
- **FR-013**: The active version's dimensions MUST come from its newest measurable file; when it has none, the model MUST say that the active version has no measurable file.
- **FR-014**: Changing the active version MUST NOT alter figures recorded on past orders, quotes (price snapshots) or completed production runs.
- **FR-015**: The system MUST refuse to delete the last file of the active version and MUST tell the operator to make another version active first.
- **FR-016**: Existing model files MUST be migrated into version "1" of their model, with that version active, without changing any model's current cost or dimensions.
- **FR-017**: Existing ways of uploading, listing, starring and deleting model files MUST keep working for current clients.

**3D viewer**

- **FR-018**: Any uploaded model file MUST be viewable in the app: meshes as a solid part, sliced files as toolpaths with a layer slider.
- **FR-019**: For a sliced export containing several plates, the operator MUST be able to choose the plate to view.
- **FR-020**: When the model has a planned printer with a known bed size, the viewer MUST draw the bed outline at true scale.
- **FR-021**: When a sliced file's header names a printer, filament or nozzle that differs from the model's planned machine, the viewer MUST state the difference.
- **FR-022**: Opening a large file MUST NOT freeze the page; above a defined size limit the viewer MUST show a reduced preview and say so.
- **FR-023**: Files recorded as local references (not uploaded) MUST show an explanation instead of the viewer.
- **FR-024**: The viewer MUST be loaded only when opened, so pages that do not use it are not slowed.

**Pinned notes**

- **FR-025**: In the viewer, an operator MUST be able to place a note on a point of a part, or on a layer of a sliced file.
- **FR-026**: A note MUST record its file, its position and facing on the part, the layer when placed on a sliced file, its text, author, creation date and status: open, resolved in a named version, or carried forward to a named version.
- **FR-027**: Pins MUST be numbered and stay attached to their point while the view is rotated, zoomed or panned.
- **FR-028**: Notes MUST also be listed beside the viewer, filterable by status, and readable without the 3D view.
- **FR-029**: When a file of a newer version is opened, the previous versions' open notes MUST appear as faded pins at their recorded position, each of which the operator can mark resolved in this version or carry forward.
- **FR-029a**: Carrying a note forward MUST create a new open note on the newer version's file, linked to the original, with the same text and position as a starting point that the operator can move; the original MUST become "carried forward to version N" and keep its own position and text unchanged.
- **FR-030**: Deleting a file MUST archive its notes, keeping them in the model's note history; open notes MUST NOT be silently dropped.

**Access and isolation**

- **FR-031**: All files, versions and notes MUST be visible only within their own tenant.
- **FR-032**: Viewer-role users MUST be able to open files and read notes but MUST NOT upload, delete, change the active version or write notes.

### Key Entities

- **Model**: the printable item; gains an active version and keeps its dimensions and cost profile, each figure with its provenance.
- **Model file version**: a numbered or labelled revision of a model's design, with a note on what changed, its upload date and uploader; groups the files of that revision, one of its sliced files marked as the print file; one version per model is active.
- **Model file**: an uploaded or referenced file (mesh, project or sliced plate) belonging to one version, with its measurement result when it has one.
- **Pinned note**: a remark placed on a file at a point on the part (and layer, for a sliced file), with text, author, date and status (open, resolved in a given version, or carried forward to a given version); a carried-forward note links to the note it continues, forming a chain across versions; archived rather than lost when its file is removed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can create a model with a source file and have its dimensions available to the packaging advisor in under 2 minutes, without leaving the create screen.
- **SC-002**: 100% of attempts to measure a sliced plate end with a message naming the file to upload instead, rather than a bare parser error.
- **SC-003**: Making a different version active never changes a past order's, quote's or production run's recorded figures (verified across all such records in tests).
- **SC-004**: After migration, every existing model's cost and dimensions are identical to before (per-record comparison reports zero differences).
- **SC-005**: A 50 MB sliced file opens in the viewer without the page becoming unresponsive for more than 1 second at a time.
- **SC-006**: An operator can open version N+1 and resolve or carry forward each open note of version N in under 30 seconds per note.
- **SC-007**: Pages that do not open the viewer load no slower than before the feature.

## Assumptions

- A "version" groups a sliced file with its source file, so a version can have both; "active" applies to the version, not to a single file. The plan decides how this maps onto the existing primary-file flag.
- Version labels default to the next number ("2", "3") and can be edited.
- Members, admins and owners can manage files, versions and notes; viewers can only read, matching the existing role hierarchy.
- The full-preview size limit defaults to 50 MB; above it the viewer shows a reduced preview. The existing 500 MB upload limit is unchanged.
- Bed sizes come from the printer records already in the app (e.g. 256 × 256 mm for an A1).
- Note positions are stored in the file's own coordinates; when a part is reshaped between versions, faded pins may not sit on the new surface and are labelled as from the earlier version.
- The existing measurement rules (multi-object note, size limits for measuring, background measuring of large files) are reused unchanged.
- Out of scope: editing models in the viewer, comparing two versions side by side, comments threads or mentions on notes, and slicing inside the app.
