# Feature Specification: Packaging Advisor

**Feature Branch**: `003-packaging-advisor`

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "Packaging advisor: given a product's/model's dimensions (entered manually or measured from uploaded STL/3MF files), suggest how to package it — box size, filler, protective wrap — and, in a second phase, use the packed size and weight to choose postage (carrier size classes, volumetric weight), pack multi-item orders into one parcel, and reuse the stored dimensions for the printer-bed fit check and Etsy listing dimensions."

## Clarifications

### Session 2026-10-25

- Q: Products can have size variants (e.g. S/M/L). Where should dimensions and the accepted packaging live? → A: On the product, with a size variant able to override both.
- Q: For a multi-item order, which box weight and size should postage use? → A: Estimate from the advisor's suggested box for the whole order; at dispatch the operator confirms the box actually used, and that is what is recorded.
- Q: Should confirming the box at dispatch also take that box (and filler) out of consumable stock? → A: Yes — confirming the parcel logs a consumable usage and lowers stock (Phase 2).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record a product's dimensions (Priority: P1)

An operator opens a product (or a model) and records its outer dimensions —
length, width and height in millimetres. The screen shows where each figure
came from: entered by the operator, or measured from an uploaded model file.
An operator's entry always takes precedence over a measured one, and is never
silently replaced by a later measurement.

**Why this priority**: Every other story depends on knowing the item's size.
Today a product carries a single "size in cm" figure, which cannot answer
"does it fit in this box?".

**Independent Test**: Enter dimensions on a product, reload, and confirm the
three figures and their source ("entered") are shown; then upload a model file
and confirm the entered figures are unchanged and the measured ones are offered
alongside.

**Acceptance Scenarios**:

1. **Given** a product with no dimensions, **When** the operator enters
   120 × 80 × 45 mm and saves, **Then** the product shows 120 × 80 × 45 mm
   marked as entered by the operator, with the date it was set.
2. **Given** a product whose dimensions were entered by the operator, **When**
   a model file measuring differently is uploaded, **Then** the entered
   dimensions remain in force and the measured dimensions are shown as a
   suggestion the operator may adopt.
3. **Given** the operator enters a zero, negative or non-numeric dimension,
   **When** they save, **Then** the save is refused with a message naming the
   field.

---

### User Story 2 - Get a box suggestion and accept it (Priority: P1)

An operator has recorded the boxes and mailers they stock, each with its
inner dimensions and empty weight. On a product with known dimensions they
press "Suggest packaging" and see the containers the item fits in, ranked
best first, each with the orientation it fits in and the room left around
it. They accept one, and it becomes the product's packaging.

**Why this priority**: This is the feature's core value — choosing a box
without measuring and guessing, and never picking one the item does not fit.

**Independent Test**: Stock three boxes of different sizes, record a product's
dimensions, request a suggestion, and confirm that only boxes the item fits
in (with the required clearance) are listed, smallest first, and that
accepting one sets it as the product's packaging.

**Acceptance Scenarios**:

1. **Given** boxes of inner size 100×100×50, 150×100×60 and 200×150×100 mm and
   a clearance of 10 mm per side, **When** the operator asks for a suggestion
   for a 120 × 70 × 30 mm product, **Then** 150×100×60 is ranked first,
   200×150×100 second, and 100×100×50 is not offered.
2. **Given** a product that only fits a box when turned on its side, **When**
   a suggestion is requested, **Then** that box is offered and the suggestion
   states the orientation it fits in.
3. **Given** no stocked container fits the product, **When** a suggestion is
   requested, **Then** the operator is told that nothing fits and given the
   minimum inner size a box would need.
4. **Given** a ranked list of suggestions, **When** the operator accepts one,
   **Then** that container (and its quantity) becomes the product's packaging,
   and the packaging cost shown on the product is the one the existing costing
   produces for that container — the advisor itself shows no cost of its own.
5. **Given** a product with no dimensions, **When** a suggestion is requested,
   **Then** the operator is told dimensions are needed first, and no
   suggestion is made.
6. **Given** a product whose accepted box no longer fits after its dimensions
   change, **When** the product is viewed, **Then** a warning says the
   accepted packaging no longer fits.

---

### User Story 3 - Measure dimensions from an uploaded model file (Priority: P2)

When an operator uploads an STL or 3MF file to a model, the system measures
the bounding box of the geometry and offers it as the model's dimensions,
marked as measured from that file. For a product made of exactly one model,
the model's dimensions are offered as the product's dimensions.

**Why this priority**: Removes the tape measure for the common single-part
item. Lower than P1 because manual entry already makes the advisor usable.

**Independent Test**: Upload a reference STL (binary and ASCII) and a
reference 3MF of known size and confirm the measured dimensions match the
known size to within 0.1 mm.

**Acceptance Scenarios**:

1. **Given** a binary or ASCII STL of a 40 × 30 × 20 mm block, **When** it is
   uploaded, **Then** the model is offered 40 × 30 × 20 mm, marked as measured
   from that file.
2. **Given** a 3MF whose build places an object with a scale or rotation,
   **When** it is uploaded, **Then** the measurement reflects the object as
   placed (after its transform), not the raw mesh.
3. **Given** a 3MF containing several separate objects, **When** it is
   uploaded, **Then** each object's size is shown, the largest single object
   is offered as the part size, and the operator is told that an assembled
   size must be entered by hand.
4. **Given** a file that cannot be read as a mesh, **When** it is uploaded,
   **Then** the upload still succeeds as today and no dimensions are offered.

---

### User Story 4 - Filler and protection suggestions (Priority: P2)

Alongside the box, the advisor suggests how much void fill to use, based on
the empty space left in the box, and — for items the operator has marked as
fragile — suggests protective wrap and a larger clearance.

**Why this priority**: Prevents breakage and gives a consistent pack, but the
box choice alone already delivers most of the value.

**Independent Test**: Stock a void-fill consumable with a stated volume per
unit, request a suggestion, and confirm the suggested quantity covers the
empty space in the chosen box.

**Acceptance Scenarios**:

1. **Given** a void-fill consumable stated as 1 litre per unit, and a chosen
   box leaving 1.6 litres of empty space, **When** the suggestion is shown,
   **Then** it recommends 2 units of void fill.
2. **Given** a product marked fragile, **When** a suggestion is requested,
   **Then** the fragile clearance is applied instead of the standard one and
   protective wrap is suggested if one is stocked.
3. **Given** no filler is stocked, **When** a suggestion is shown, **Then**
   the empty space is still reported and no filler quantity is suggested.

---

### User Story 5 - Postage uses the packed parcel (Priority: P3, Phase 2)

Postage is chosen from the parcel as it actually ships: the product plus its
box and filler, and the parcel's outer size. Shipping profiles can state the
size limits of a carrier's format (for example a large letter of at most
353 × 250 × 25 mm), and a volumetric divisor for couriers that charge by
volume, so a parcel that is light but too thick for a large letter is priced
as a parcel.

**Why this priority**: UK carriers price by format first and weight second.
Today postage is chosen by product weight alone, which can understate the
cost of a free-shipping order. It depends on Stories 1–2 being in place.

**Independent Test**: Configure a large-letter profile limited to 25 mm thick
and a small-parcel profile; post an order for a 200 g item in a 30 mm deep
box and confirm the small-parcel postage is chosen.

**Acceptance Scenarios**:

1. **Given** a product weighing 180 g whose packaging weighs 40 g, **When**
   postage is determined, **Then** the 220 g packed weight is used to choose
   the weight bracket.
2. **Given** a large-letter profile limited to 353 × 250 × 25 mm and a parcel
   whose outer size is 160 × 110 × 70 mm, **When** postage is determined,
   **Then** the large-letter profile is not chosen.
3. **Given** a courier profile with a volumetric divisor of 5000 and a parcel
   of 400 × 300 × 200 mm weighing 1 kg, **When** postage is determined,
   **Then** the chargeable weight is the 4.8 kg volumetric weight.
4. **Given** shipping profiles with no size limits, **When** postage is
   determined, **Then** they are chosen by weight exactly as today.
5. **Given** an order already settled with recorded postage, **When** the
   packaging or profiles change, **Then** that order's recorded postage does
   not change.
6. **Given** an order whose suggested box is 200×150×100 mm, **When** the
   operator confirms at dispatch that a 250×200×100 mm box was used, **Then**
   the recorded postage is determined from the 250×200×100 mm box and its
   weight, and the earlier figure is shown only as the estimate.
7. **Given** 12 of a box in stock, **When** an order is dispatched with one of
   that box and 2 units of void fill confirmed, **Then** the box stock is 11,
   the void fill stock falls by 2, and confirming the same order again does
   not deduct a second time.

---

### User Story 6 - One box for a multi-item order (Priority: P3, Phase 2)

For an order with several lines, the operator asks which box to ship it in.
The advisor suggests a single container that holds every item, or, if none
does, the fewest containers that do.

**Why this priority**: An order is one parcel, and choosing its box by eye
for several items is where mistakes happen; but single-item orders are the
majority.

**Independent Test**: Create an order of two products that fit together in
one stocked box and confirm that box is suggested; add a third that cannot fit
and confirm a split is proposed.

**Acceptance Scenarios**:

1. **Given** an order of two items that fit together in a stocked box,
   **When** a suggestion is requested, **Then** one box is suggested holding
   both, with the arrangement stated.
2. **Given** an order whose items cannot share any stocked box, **When** a
   suggestion is requested, **Then** a split into the fewest boxes is
   proposed, each with its contents.
3. **Given** an order line with no recorded dimensions, **When** a suggestion
   is requested, **Then** the operator is told which product lacks
   dimensions, and no suggestion is made.

---

### User Story 7 - Dimensions reused elsewhere (Priority: P3, Phase 2)

Once a model has dimensions, the print queue refuses to assign it to a
printer whose bed is too small, and an Etsy listing shows the product's
dimensions instead of a single size figure.

**Why this priority**: Free value from data the feature already collects;
neither is needed for packaging.

**Independent Test**: Queue a model larger than a printer's bed and confirm
that printer is not offered; sync a product with dimensions to Etsy and
confirm the listing shows them.

**Acceptance Scenarios**:

1. **Given** a model measuring 300 mm on its longest side and a printer with
   a 256 mm bed, **When** printers are matched for it, **Then** that printer
   is excluded with the reason stated.
2. **Given** a model with no dimensions, **When** printers are matched,
   **Then** matching behaves as today.
3. **Given** a product with dimensions, **When** it is synced to Etsy,
   **Then** the listing shows length × width × height.

---

### Edge Cases

- An item exactly equal to the box's inner size minus clearance fits; one
  0.1 mm larger does not.
- A box recorded without all three inner dimensions is never suggested, and
  the box list says which boxes are incomplete.
- A container that is out of stock is still suggested but marked out of
  stock, ranked after in-stock containers that fit.
- Two containers of identical size are ranked by lower cost per unit as the
  existing costing reports it; with no cost recorded, by name.
- A soft mailer is recorded with its usable flat size and maximum thickness,
  and is checked the same way as a box.
- A model file in units other than millimetres (a 3MF declaring inches or
  centimetres) is converted to millimetres before being offered.
- A large file (over 25 MB) is measured after the upload returns, and its
  measurement appears when ready; a file over 200 MB is not measured and says
  so. If measurement fails or is abandoned, the upload still succeeds and no
  dimensions are offered.
- An order line of quantity 3 of one product is three units, not one: it is
  packed as a multi-item parcel, never as the product's single-unit box.
- A product's dimensions change after packaging was accepted: the accepted
  packaging is kept but flagged if it no longer fits (Story 2, scenario 6).
- A viewer-role user can see suggestions but cannot accept one or change
  dimensions.
- The clearance setting is zero: items fit boxes exactly their size.

## Requirements *(mandatory)*

### Functional Requirements

**Dimensions (MVP)**

- **FR-001**: The system MUST let an operator record length, width and height
  in millimetres, to 0.1 mm, on a product and on a model. A size variant of
  a product MAY override the product's dimensions; a variant without an
  override uses the product's.
- **FR-002**: Every recorded dimension set MUST carry its source — entered by
  the operator, or measured from a named model file — and when it was set.
- **FR-003**: Dimensions entered by an operator MUST take precedence over
  measured ones and MUST NOT be replaced by a later measurement without the
  operator adopting it.
- **FR-004**: The system MUST reject a dimension that is zero, negative or not
  a number.
- **FR-005**: The existing single "size in cm" figure MUST continue to work for
  every screen and integration that reads it today until each is moved to the
  new dimensions.

**Measurement from files (MVP)**

- **FR-006**: On upload of an STL (binary or ASCII) or 3MF file to a model,
  the system MUST measure the bounding box of its geometry and offer it as the
  model's dimensions, marked as measured from that file.
- **FR-007**: For 3MF files, measurement MUST apply each object's placement
  (scale, rotation, translation) and the file's declared unit.
- **FR-008**: For a 3MF with several objects, the system MUST show each
  object's size, offer the largest single object as the part size, and tell
  the operator an assembled size must be entered by hand.
- **FR-009**: A product made of exactly one model at quantity one MUST be
  offered that model's dimensions; any other product MUST NOT receive
  dimensions automatically.
- **FR-010**: A file that cannot be measured MUST NOT fail its upload.

**Packaging catalogue (MVP)**

- **FR-011**: The system MUST let an operator record, on a stocked consumable,
  its packaging kind (box, mailer, void fill, protective wrap), its inner
  length, width and height in millimetres, and its empty weight in grams.
- **FR-012**: For void fill, the system MUST let the operator record the
  volume one unit fills.
- **FR-013**: Packaging attributes MUST be optional, so existing consumables
  that are not packaging are unaffected.
- **FR-038**: Once a container's inner size, wall thickness and empty weight
  decide postage (Phase 2), each MUST carry where it came from (measured by
  the operator, or assumed) and when it was set, like every other figure that
  decides a cost.

**Advisor (MVP)**

- **FR-014**: Given a product with dimensions, the system MUST list every box
  or mailer the product fits in, trying all six orientations, with the
  configured clearance on every side.
- **FR-015**: The clearance MUST be a tenant setting, with a separate fragile
  clearance; the operator's setting MUST be the one used (no hidden default
  overriding it).
- **FR-016**: Suggestions MUST be ranked by smallest inner volume first; ties
  by lower unit cost as the existing costing reports it; then by name.
  In-stock containers MUST rank before out-of-stock ones.
- **FR-017**: Each suggestion MUST state the orientation used, the room left
  on each axis, and the empty volume remaining.
- **FR-018**: When nothing fits, the system MUST say so and state the minimum
  inner size a container would need.
- **FR-019**: The system MUST suggest a quantity of void fill that covers the
  empty volume, rounded up to whole units, when a void-fill consumable with a
  stated unit volume is stocked.
- **FR-020**: The system MUST let an operator mark a product as fragile; for a
  fragile product the advisor MUST apply the fragile clearance and suggest
  protective wrap when one is stocked.
- **FR-021**: The advisor MUST NOT compute, show or store any cost of its own;
  any cost shown next to a suggestion MUST come from the existing costing.
- **FR-022**: Suggestions MUST be computed when requested and MUST NOT be
  stored.
- **FR-023**: An operator with write permission MUST be able to accept a
  suggestion, which sets the packaging container and quantity of the product,
  or of the size variant the suggestion was made for (overriding the
  product's); a read-only user MUST NOT. Suggestions for a variant MUST use
  the variant's effective dimensions.
- **FR-039**: Where a variant's accepted packaging differs from the
  product's, the variant MUST state that its cost breakdown uses the
  product's packaging, because variant packaging is not costed; no screen may
  show a variant packaging cost of its own.
- **FR-024**: A product whose accepted packaging no longer fits its current
  dimensions MUST show a warning.

**Postage (Phase 2)**

- **FR-025**: When choosing postage, the parcel weight MUST be the products'
  weight plus the weight of the parcel's packaging container(s) and filler. A
  recorded packaging item whose weight is missing MUST be reported as an
  unknown, not treated as zero.
  Before dispatch, the parcel is the one the advisor suggests for the whole
  order; for an order of exactly one unit it is that unit's accepted
  packaging. Any order of more than one unit, including one line of
  quantity above one, MUST use the order-level suggestion; until order-level
  packing (Story 6) is released, such orders keep today's weight-only postage,
  flagged as not including packaging. A unit with no packaging recorded at
  all also keeps today's weight-only postage, flagged the same way; packaging
  that is recorded but has no weight makes the postage unknown. This is an
  estimate and MUST be shown as one.
- **FR-036**: At dispatch, the operator MUST be able to confirm the
  container(s) actually used, pre-filled with the suggestion. The postage
  recorded for the order MUST be determined from the confirmed parcel, and
  the confirmed packaging MUST be recorded once with the order and MUST NOT be
  restated afterwards.
- **FR-037**: Confirming the parcel at dispatch MUST record a usage of each
  confirmed container and filler against that order and reduce its stock by
  the quantity used, exactly once per order; stock MAY go below zero, and
  that MUST be shown rather than blocking dispatch.
- **FR-026**: A shipping profile MUST be able to state maximum length, width,
  height (any orientation) and a volumetric divisor; profiles with none of
  these MUST be chosen by weight alone, exactly as today. Where several
  profiles cover a parcel, size-limited profiles MUST be considered first,
  cheapest first; profiles without limits MUST keep today's order, so a
  tenant with no size-limited profile sees no change.
- **FR-027**: A profile with size limits MUST only be chosen for a parcel
  whose outer size is known and within them.
- **FR-028**: Where a profile has a volumetric divisor, the chargeable weight
  MUST be the greater of actual weight and volume ÷ divisor, using the
  carriers' convention of cubic centimetres ÷ divisor = kilograms.
- **FR-029**: Size limits and divisors MUST be effective-dated like the rest
  of the shipping profile; a change MUST supersede, not edit, and MUST NOT
  move the recorded postage of a settled order.
- **FR-030**: Postage MUST continue to be decided in one place; packed weight
  and size classes MUST be part of that decision, not a second calculation
  beside it. The packed parcel (weight and outer size) MUST be assembled by
  one calculation, used both for the estimate before dispatch and for the
  parcel confirmed at dispatch.

**Multi-item orders (Phase 2)**

- **FR-031**: For an order, the system MUST suggest one container that holds
  every line's items, or the fewest containers that do, each with its
  contents.
- **FR-032**: If any line lacks dimensions, the system MUST name it and make no
  suggestion.

**Reuse (Phase 2)**

- **FR-033**: Printer matching MUST exclude a printer whose bed cannot hold the
  model's footprint (in either horizontal rotation) and height, stating why;
  models without dimensions MUST match as today.
- **FR-034**: An Etsy listing MUST show a product's length × width × height
  when they are known, falling back to the existing size figure otherwise.

**Isolation**

- **FR-035**: All new records MUST belong to a tenant and MUST be invisible to
  every other tenant, enforced at the database level.

### Key Entities

- **Item dimensions**: length, width, height (mm) of a product or model, with
  source (entered / measured), the file it was measured from, and when set.
- **Measured file geometry**: per uploaded model file, the size of each object
  and of the whole build, as a suggestion only.
- **Packaging attributes of a consumable**: kind (box, mailer, void fill,
  protective wrap), inner length/width/height, empty weight, unit fill volume.
- **Packaging settings**: per-tenant standard and fragile clearance.
- **Packaging suggestion** (not stored): container, orientation, room per
  axis, empty volume, filler and wrap quantities, warnings.
- **Product packaging choice** (existing): the container and quantity the
  operator accepted, on the product, optionally overridden per size variant.
- **Variant dimension/packaging override**: optional dimensions and packaging
  choice on a size variant, falling back to the product's when absent.
- **Order parcel record** (Phase 2): the container(s) and filler the operator
  confirmed at dispatch, with their weight and outer size; written once.
- **Shipping profile size class** (Phase 2): maximum outer size and volumetric
  divisor on an existing effective-dated shipping profile.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with dimensions recorded chooses a box for a product
  in under 30 seconds, without measuring.
- **SC-002**: No suggested container is one the item does not fit in, across
  every orientation and clearance tested (zero false fits).
- **SC-003**: Dimensions measured from reference STL and 3MF files match their
  known size to within 0.1 mm on every axis.
- **SC-004**: At least 80% of single-part products receive dimensions from
  their uploaded file without manual entry.
- **SC-005**: After Phase 2, no order whose parcel exceeds a format's size
  limit is priced at that format's postage.
- **SC-006**: Recorded postage of every order settled before Phase 2 is
  unchanged after it is released.
- **SC-007**: Uploading a model file of up to 25 MB, measurement included,
  takes under 1 second longer than the same upload without measurement; a
  larger file's upload is not delayed by measurement at all.

## Assumptions

- The clearance defaults to 10 mm per side (20 mm for fragile items) when a
  tenant first uses the feature, and is then the operator's to change.
- Fragility is marked by the operator; the system does not infer it from
  geometry.
- Items are treated as their bounding box; the advisor does not nest items
  into irregular shapes or exploit hollow space.
- Multi-item packing aims for a practical arrangement, not a mathematically
  optimal one; the operator can always override the choice.
- Carrier formats and their limits are entered by the operator, as weight
  brackets are today; no carrier's tables are preloaded.
- Weights stay in grams and dimensions in millimetres; no imperial display is
  in scope.
- A dimension's source ("entered" or "measured") is its own vocabulary and is
  not the pricing-input provenance (observed / measured / policy / assumed):
  an item's dimensions are not a cost input. Container figures that decide
  postage use the pricing provenance (FR-038).
- Costing does not price variants today; a variant's own packaging affects
  packing and postage only (FR-039).
- Measurement covers STL and 3MF only; G-code and other formats are out of
  scope.
- Depends on the existing product packaging link, consumables catalogue,
  shipping profiles, model file upload and print-queue printer matching.
