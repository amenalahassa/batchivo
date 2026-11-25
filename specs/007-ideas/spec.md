# Feature Specification: Ideas — capture, brainstorm and iterate on product ideas, then turn one into a model or product

**Feature Branch**: `007-ideas`

**Created**: 2026-11-23

**Status**: Draft

**Input**: User description: "Ideas: a place to capture, brainstorm and iterate on product ideas, then turn one into a model or a product." Full prompt: `specs/backlog.md`, section "Ideas: capture, brainstorm and iterate on product ideas, then turn one into a model or product". Architecture: `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §3, §4 and §9.

## Clarifications

### Session 2026-11-23

- Q: Should an idea's images be served to anyone who has their address, as product images are today, or only to a signed-in member of the shop that owns the idea? → A: Only to a signed-in member of the owning shop; otherwise refused, or "not found" for another shop.
- Q: For bulk creation from the pain-point report, should Batchivo read the report file itself, receive a structured list of problems produced by an agent or the report tooling, or both? → A: Both: the API takes a structured list; the screen also accepts the report file, turns it into that list and shows a preview before importing (source link = the problem's first evidence link).
- Q: When a report problem arrives with only its total (e.g. 20/25) and not the five separate scores, what does the imported idea keep? → A: The total as a separate "report score" with its origin; it is displayed and sorted on until all five scores are entered, then the computed total replaces it.
- Q: Can a member convert an idea to a product when creating a product from the products screen requires admin? → A: No — converting to a model is open to members and above; converting to a product requires admin and above, as creating a product does.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Capture an idea and find it again (Priority: P1)

An operator has an idea for a new printed product — a clip that holds a car sun
visor, a key turner for people with arthritis. They open "Ideas" from the main
navigation, choose "New idea", type a title and a few lines on the problem and
the idea, pick where it came from (their own idea, a customer, the pain-point
report, something else) with an optional link, add tags, and score it on the
five criteria the pain-point report uses (frequency, frustration, printability,
gap, willingness to pay, 1 to 5 each). The idea lands in "Inbox". Later they open
the board and see their ideas in columns by status — Inbox, Exploring,
Validating, Ready, Parked, Dropped, Converted — each card showing its cover
image, total score and tags. They move an idea from one status to another as it
matures. With a few hundred ideas, they switch to the list view, search by
words, filter by status, tag and source, and sort by last update or score.

**Why this priority**: Ideas today live in notes, chats and report files and are
lost by the time a model is made. A place to capture, score and find them is
useful on its own, before any timeline or conversion exists.

**Independent Test**: As a 3D-print shop, open Ideas from the navigation, create
an idea with title, summary, source, tags and five scores, see it in the Inbox
column with its total, move it to Exploring, then find it in the list view by a
word of its title, by tag, and at the top when sorting by score.

**Acceptance Scenarios**:

1. **Given** a 3D-print shop (new or existing), **When** the operator looks at the main navigation, **Then** an "Ideas" entry is shown, and a shop of another type does not get it unless it enables the module.
2. **Given** the operator creates an idea with only a title, **When** it is saved, **Then** it is in status Inbox, source "manual", no tags, no scores, and its total shows as "not scored" rather than 0.
3. **Given** an idea scored 4, 5, 3, 4, 2, **When** it is shown on the board or the list, **Then** its total reads 18/25.
4. **Given** an idea with a score of 6 or 0 on any criterion, **When** the operator saves it, **Then** it is refused with a message naming the criterion and the 1–5 range.
5. **Given** ideas in several statuses, **When** the operator opens the board, **Then** each status is a column (Inbox, Exploring, Validating, Ready, Parked, Dropped, Converted), each column shows its count and its first ideas, and further ideas load on demand rather than all at once.
6. **Given** 300 ideas, **When** the operator searches the list view for a word that appears in 3 titles or summaries, **Then** exactly those 3 are listed, and filtering by a tag, a status or a source narrows the list accordingly.
7. **Given** the list sorted by score, **When** it is shown, **Then** ideas with the highest total come first and unscored ideas come last.
8. **Given** an idea imported with report score 20/25 and no separate scores, **When** it is shown and sorted, **Then** it reads "report score 20/25" and sorts as 20; **When** the operator then enters all five scores totalling 17, **Then** it shows 17/25 and sorts as 17, and the report score stays visible as history.
9. **Given** an idea, **When** the operator changes its status, title, summary, tags, source or scores, **Then** the change is saved and its "last updated" moves to now.
10. **Given** an idea the operator no longer wants, **When** they archive it, **Then** it disappears from the board and the list but is not destroyed, and can be shown again with an "archived" filter and restored.
11. **Given** two shops, **When** an operator of one lists, opens or edits ideas, **Then** they never see or reach an idea of the other shop.

---

### User Story 2 - Brainstorm on an idea's timeline, iteration by iteration (Priority: P1)

The operator opens an idea and sees its page: the header (title, status, scores,
tags, source) and below it a timeline of everything gathered about the idea,
newest first. A composer at the top adds an entry: a note in markdown, one or
several images (picked from disk, dropped onto the page, or pasted from the
clipboard), a link with a short comment, a sketch (an image marked as a sketch),
a measurement (a short text such as "visor thickness 4.2 mm") or a decision
("going for a clip-on, not a screw"). Entries belong to the idea's current
iteration. When the design changes direction, the operator starts the next
iteration with a short note ("iteration 2: clip-on instead of screw"); the
timeline then groups entries under "Iteration 2", "Iteration 1"… Entries can be
edited, pinned (pinned entries show first in their iteration and are what
conversion copies) and archived. One image is chosen as the idea's cover, shown
on the board. A gallery tab shows every image of the idea across all iterations.

**Why this priority**: This is where an idea's reasoning and pictures stop being
lost. Together with Story 1 it is the minimum useful Ideas module.

**Independent Test**: On an idea, add a note, upload two images at once, paste a
third from the clipboard, add a link and a decision; start iteration 2 with a
note and add one more image; check the timeline groups entries under Iteration 2
and Iteration 1, the gallery shows all four images, pin an entry, set an image as
cover and see it on the board card, then archive an entry and see it leave the
timeline.

**Acceptance Scenarios**:

1. **Given** an idea at iteration 1, **When** the operator adds a note with markdown (headings, lists, links), **Then** it appears at the top of the timeline under Iteration 1 with its author and time, rendered as formatted text.
2. **Given** the composer, **When** the operator selects three images at once, or drops them onto the page, or pastes one from the clipboard, **Then** each becomes an image entry with a thumbnail, in the current iteration.
3. **Given** a file that is not a JPEG, PNG or WebP image, or an image larger than 10 MB, **When** it is uploaded, **Then** it is refused with a message naming the file and the reason, and the other files of the same upload are still saved.
4. **Given** an idea at iteration 2, **When** the operator chooses "Start next iteration" with the note "clip-on instead of screw", **Then** the idea moves to iteration 3, that note is the first entry of Iteration 3, and later entries go to Iteration 3.
5. **Given** entries in iterations 1, 2 and 3, **When** the timeline is shown, **Then** entries are grouped by iteration, latest iteration first, and within an iteration pinned entries come first, then newest first.
6. **Given** an entry, **When** the operator edits its text or link, **Then** the change is saved and the entry shows it was edited; **When** they pin it, **Then** it moves to the top of its iteration; **When** they archive it, **Then** it leaves the timeline and the gallery but stays recoverable.
7. **Given** an image entry, **When** the operator sets it as cover, **Then** the board card and the idea header show that image; **Given** the cover entry is archived, **Then** the idea has no cover until another is chosen.
8. **Given** an idea with no cover and at least one image, **When** the board is shown, **Then** the card shows no image (the cover is only what the operator chose).
9. **Given** images across iterations, **When** the operator opens the gallery, **Then** every non-archived image of the idea is shown with its iteration, and opening one shows it large.
10. **Given** an idea of another shop, **When** an operator tries to add, edit or read its entries or images, **Then** it is as if the idea did not exist.
11. **Given** the address of an idea image, **When** it is opened without being signed in, **Then** the image is not returned.

---

### User Story 3 - Turn an idea into a model or a product (Priority: P2)

When an idea is ready, the operator clicks "Convert". "Convert to model" creates
a model from the idea — its name from the idea's title (editable), its
description from the summary, its image from the cover — and links them both
ways. "Convert to product" creates the product, a model for it and the product's
bill-of-materials line (one of that model) exactly as creating a product with a
model does today, and copies the idea's pinned images to the product's images.
The idea becomes "Converted" and shows links to the model and product it became;
the model's and product's pages show "From idea: <title>" with a link back.

**Why this priority**: Saves retyping and gives traceability from a product back
to the reasoning behind it, but Stories 1 and 2 are useful without it.

**Independent Test**: Convert an idea with a cover and two pinned images to a
product; check a new model and product exist, the product's bill of materials
holds one of that model, the product has the two pinned images, the idea shows
status Converted with links to both, and both show the idea they came from.

**Acceptance Scenarios**:

1. **Given** an idea with title "Sun visor clip", a summary and a cover image, **When** the operator converts it to a model accepting the defaults, **Then** a model named "Sun visor clip" exists with the summary as description and the cover as its image, the idea is Converted and links to the model, and the model page shows "From idea: Sun visor clip".
2. **Given** an idea with two pinned images, **When** the operator converts it to a product, **Then** a model and a product are created, the product's bill of materials holds that model with quantity 1, the product has the two pinned images (the cover first, as primary), and the idea links to both.
3. **Given** the conversion dialog, **When** it opens, **Then** the name and the product or model reference (SKU) are prefilled with the next available reference and can be edited, and the operator can choose not to copy images.
4. **Given** a SKU that already exists, **When** the operator confirms the conversion, **Then** nothing is created, the idea is unchanged, and the operator is told the SKU is taken.
5. **Given** any failure while converting, **When** the conversion stops, **Then** no model, product or image copy is left behind and the idea keeps its status.
6. **Given** an idea already converted to a model, **When** the operator converts it to a product, **Then** the product uses the existing linked model rather than a second one, and the idea then links to both.
7. **Given** an idea already converted to a product, **When** the operator looks at the Convert button, **Then** it says the idea was already converted and links to the product instead of converting again.
8. **Given** the model or product created from an idea is later deleted, **When** the idea is opened, **Then** it still loads and shows that its model or product no longer exists.
9. **Given** existing models and products not created from an idea, **When** they are read, created or edited through their existing screens and API, **Then** they behave exactly as before.

---

### User Story 4 - Import ideas from the pain-point report (Priority: P3)

Regularly, the pain-point report ranks everyday problems a printed object could
solve. The operator imports a report into Ideas: each problem of the report
becomes an idea in Inbox with its title, a summary (the product idea and the
evidence), its score, tags (its niche) and source "pain-point report" with its
source link. Importing the same report twice, or a later report that repeats a
problem, does not create duplicates: a problem already imported from the same
source link is skipped and reported as skipped.

**Why this priority**: Saves copying ten ideas a week by hand, but the module is
complete without it.

**Independent Test**: Drop a report file with 10 problems on the import screen, check the preview lists 10 to create, confirm, and see 10 new Inbox ideas
with source "pain-point report", their scores and links; import it again and see
0 created, 10 skipped.

**Acceptance Scenarios**:

1. **Given** a report file with 10 problems, **When** the operator pastes or drops it on the import screen, **Then** a preview lists the 10 problems with their title, score, niche and source link and nothing is created yet; **When** they confirm, **Then** 10 ideas are created in Inbox with source "pain-point report", their source link, their report score (e.g. "report score 20/25", five separate scores empty), niche tag and summary, and the operator sees "10 created, 0 skipped".
2. **Given** the same report imported again, **When** the import runs, **Then** no idea is created and the operator sees "0 created, 10 skipped" with the skipped titles.
3. **Given** a report where 2 of 10 problems have a source link already imported (even if that idea has since been archived or converted), **When** it is imported, **Then** 8 are created and 2 skipped.
4. **Given** a report entry without a title, or with a score outside the allowed range, **When** it is imported, **Then** that entry is refused with its reason, and the valid entries are still imported.
5. **Given** a structured list of problems sent through the API (as an agent does), **When** it is imported, **Then** the same creation, skip and refusal rules apply as for the report file.
6. **Given** a pasted text that contains no recognisable problem section, **When** the preview is built, **Then** the operator is told no problem was found and nothing is imported.
7. **Given** two shops importing the same report, **When** each imports it, **Then** each gets its own ideas; a source link imported in one shop does not cause a skip in the other.

---

### Edge Cases

- An idea with no images is converted: the model or product gets no image; conversion still succeeds.
- An image entry's file is missing from storage (deleted by hand): the entry still shows, with a "missing image" placeholder; conversion copies the images that exist and reports the ones it could not copy.
- The operator pastes text (not an image) into the composer: it goes into the note field, not into an upload.
- Two operators edit the same idea at once: the last save wins for header fields; entries are separate records and are never lost.
- A tag is typed with different case or spacing ("Car", " car "): tags are trimmed and compared without case, so the idea holds one "car" tag.
- A source link is given without a scheme or with a scheme other than http or https: it is refused.
- The board is opened by a shop with no ideas: each column shows an empty state with "New idea" and "Import report".
- An idea is moved to "Converted" by hand without converting: allowed only through conversion; the status picker does not offer Converted, and an idea's status can leave Converted only by being set back by the operator (links are kept).
- Archiving an idea that was converted: the model and product are untouched and keep showing the idea they came from (marked archived).
- A shop disables the Ideas module: the menu entry and pages disappear; data is kept and comes back when the module is enabled again.
- A viewer (read-only role) opens Ideas: they can read ideas, entries and images but cannot create, edit, archive, import or convert.

## Requirements *(mandatory)*

### Functional Requirements

**Module and navigation**

- **FR-001**: The system MUST provide an "Ideas" module with its own navigation entry and pages, enabled by default for 3D-printing shops (new and existing) and available to other shop types when they enable it.
- **FR-002**: Members and above MUST be able to create, edit, archive, import ideas and their entries and convert an idea to a model; converting an idea to a product MUST require the same role as creating a product on the products screen (admin and above), and a member sees that action disabled with the reason; viewers MUST be able to read only.

**Ideas**

- **FR-003**: Each idea MUST have a title (required, 1–200 characters), a summary (optional, markdown), a status (inbox, exploring, validating, ready, converted, parked, dropped; inbox by default), a source (manual, pain-point report, customer, other; manual by default), an optional source link (http or https), a list of tags, and five optional scores (frequency, frustration, printability, gap, willingness to pay), each a whole number from 1 to 5.
- **FR-004**: The system MUST show an idea's total score as the sum of its five scores out of 25 when all five are set, MUST NOT store that total separately from the scores it is computed from, and MUST show an idea with missing scores as not (fully) scored rather than as a low total.
- **FR-004a**: An idea MAY carry a report score — the total out of 25 (0–25) given by the pain-point report when the five separate scores are not known — shown as "report score" with its origin. While the five scores are not all set, the report score is the idea's displayed and sortable score; once all five are set, the computed total replaces it for display and sorting, and the report score is kept as recorded and never changed by the system.
- **FR-005**: The system MUST record who created each idea and when, and when it was last updated.
- **FR-006**: Operators MUST be able to archive an idea and restore it; archived ideas MUST be hidden from the board and list unless an "archived" filter is chosen.
- **FR-007**: The status "converted" MUST be set only by a conversion; the operator MAY move a converted idea to another status, and its conversion links MUST be kept.

**Board and list**

- **FR-008**: The board MUST show one column per status with its count, each card showing title, cover image (if any), total score and tags; each column MUST load a first page of ideas and load more on demand.
- **FR-009**: The list view MUST search title and summary, filter by status, tag, source and archived state, sort by last updated (default) or score (the computed total, else the report score; ideas with neither last), and paginate.
- **FR-010**: Board and list MUST stay responsive with at least 500 ideas in a shop: no screen loads all ideas at once.

**Timeline and entries**

- **FR-011**: An idea MUST hold a timeline of entries, each with a kind (note, image, link, sketch, measurement, decision, generation), an iteration number, optional markdown text, and for image and sketch entries the stored image with its thumbnail, file type, original filename and size, and for link entries the link.
- **FR-012**: The kind "generation" and an optional reference to the generation job that produced the entry MUST exist in the data from this feature on, so that the later AI generation feature can add generated entries without reshaping the timeline; this feature MUST NOT offer creating generation entries from the composer.
- **FR-013**: Each entry MUST record its author and creation time, and show that it was edited when its text or link changed after creation.
- **FR-014**: Operators MUST be able to add notes, links, measurements and decisions, and to upload one or several JPEG, PNG or WebP images (up to 10 MB each) as image or sketch entries, by file picker, drag-and-drop and clipboard paste; each refused file MUST be reported with its reason without blocking the others.
- **FR-015**: Each idea MUST have a current iteration (starting at 1); new entries MUST go to the current iteration; operators MUST be able to start the next iteration with an optional note that becomes its first entry.
- **FR-016**: Operators MUST be able to edit an entry's text and link, pin and unpin it, and archive and restore it; archived entries MUST be hidden from the timeline and gallery.
- **FR-017**: The timeline MUST group entries by iteration (latest first) and, within an iteration, show pinned entries first and then newest first.
- **FR-018**: Operators MUST be able to set one non-archived image or sketch entry as the idea's cover, or clear it; archiving the cover entry MUST clear the cover.
- **FR-019**: A gallery MUST show every non-archived image and sketch of the idea across iterations, with its iteration.

**Image storage**

- **FR-020**: Idea images MUST be stored through the same image storage as product images, with the same file types, size limit and thumbnails, in a location keyed by owner (ideas apart from products).
- **FR-021**: Existing and new product images MUST keep exactly their current storage locations and addresses; no stored product image address changes.
- **FR-022**: Idea images (full size and thumbnails) MUST be served only to a signed-in user of the shop that owns the idea; a request without a valid sign-in MUST be refused, and a request from another shop MUST be answered as if the image did not exist. Product images keep being served as today.

**Conversion**

- **FR-023**: Operators MUST be able to convert an idea to a model: the model's name defaults to the idea's title, its description to the summary, and its image to the cover; name and reference are editable before confirming.
- **FR-024**: Operators MUST be able to convert an idea to a product: the product is created through the same product creation as the products screen, with its model (the idea's existing linked model if any, else a new one made as in FR-023) as a bill-of-materials line of quantity 1; the conversion MUST NOT write bill-of-materials lines by any other path.
- **FR-025**: Converting to a product MUST copy the idea's pinned images (the cover first, as the primary image) to the product's images, unless the operator chooses not to copy images.
- **FR-026**: A conversion MUST be all-or-nothing: on any failure, no model, product, bill-of-materials line or copied image is left, and the idea is unchanged.
- **FR-027**: After a conversion, the idea MUST be in status Converted and link to the model and/or product; the model and the product MUST record the idea they came from and show it on their pages.
- **FR-028**: An idea already converted to a product MUST NOT be converted again; an idea converted to a model only MAY be converted to a product, which reuses its model.
- **FR-029**: Models and products MUST keep their current behaviour and contracts; the idea they came from is an optional addition that is empty for all existing records.
- **FR-030**: If the model or product an idea was converted to is deleted, the idea MUST remain readable and show the link as gone.

**Import**

- **FR-031**: Operators MUST be able to create ideas in bulk from a pain-point report, each in status Inbox with source "pain-point report". The import MUST accept a structured list of problems (title, summary, either the five scores or a report total, tags, source link) — the form agents and the later MCP server use — and the Ideas screen MUST also accept the report file itself (the markdown report, pasted or dropped), turn each of its problems into that list (title from the problem heading, summary from the product idea, quote, feasibility and evidence links, tag from the niche, source link = the problem's first evidence link) and show a preview (to create / to skip / refused) before anything is imported.
- **FR-032**: The import MUST skip an entry whose source link matches an idea of the same shop already imported from that link (archived and converted ideas included), and MUST report created, skipped (with titles) and refused (with reasons) counts.
- **FR-033**: Invalid entries in an import MUST be refused individually without blocking the valid ones.

**Isolation and history**

- **FR-034**: Ideas, entries and their images MUST belong to exactly one shop; no listing, read, write, image access, import duplicate check or conversion MAY cross shops.

### Key Entities

- **Idea**: a product idea of one shop. Title, summary, status, source and source link, tags, five scores (total derived), optional report score (total given by an imported report, kept with its origin), current iteration, optional cover (one of its image entries), optional links to the model and product it became, who created it, created/updated/archived times.
- **Idea entry**: one item of an idea's timeline. Kind (note, image, link, sketch, measurement, decision, generation), iteration, text, image (address, thumbnail, file type, original name, size), link, optional generation job reference (filled by a later feature), pinned flag, author, created/edited/archived times.
- **Model** (existing): gains an optional "came from idea" link.
- **Product** (existing): gains an optional "came from idea" link.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator captures a new idea with title, source, tags and scores in under 1 minute.
- **SC-002**: With 500 ideas in a shop, the board and the list each show their first page, and a search or filter result, in under 2 seconds.
- **SC-003**: Adding five images to an idea takes one action (one selection, one drop or one paste per image) and no form per image.
- **SC-004**: Turning a ready idea into a product with its model, bill-of-materials line and images takes one dialog and under 30 seconds, with no field retyped.
- **SC-005**: Importing a report of 10 problems takes under 1 minute; re-importing it creates 0 duplicates.
- **SC-006**: 100% of products and models created from an idea show the idea they came from, and 100% of converted ideas show what they became.
- **SC-007**: After the release, 100% of existing product images still open at their previous addresses.

## Assumptions

- "Shop" is a tenant; "operator" is a signed-in user of that tenant. Role rules follow the existing roles (viewer reads only; member and above write), as for model file notes.
- Ideas are an operator tool only: nothing of an idea is shown on the public shop.
- The scoring grid is the pain-point report's (five criteria, 1–5 each, total out of 25); scores are optional so a quick idea can be captured unscored.
- Archive is the only removal offered; there is no permanent delete of ideas or entries in this feature (images of archived entries stay in storage).
- A sketch is an uploaded image marked as a sketch; drawing in the browser is out of scope.
- A measurement is a short free-text entry; structured measurement values arrive with the Preflight foundations feature (009), which will also attach a design brief to an idea and follow it to the model.
- Generation entries are produced by the Generative AI feature (008); this feature only reserves their kind and job reference. The "Generate" actions on the idea page arrive with 008.
- The MCP server feature (010) will expose ideas through the same API this feature provides; no agent-specific endpoint is built here.
- The product and model references (SKUs) for conversion default to the next available reference from the existing SKU generator.
- The module is gated in the navigation and pages as existing modules are; API routes are not gated per module, as today (architecture §9).
- Model thumbnails and the shop logo, which today are stored alongside product images, keep their current locations and addresses.
