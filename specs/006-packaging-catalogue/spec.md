# Feature Specification: Packaging Page and Default Packaging and Postage Catalogue

**Feature Branch**: `006-packaging-catalogue`

**Created**: 2026-11-03

**Status**: Draft

## Clarifications

### Session 2026-11-03

- Q: Should catalogue items come with a typical purchase price, or none until the operator enters theirs? → A: A typical price, marked assumed and flagged in the margin.
- Q: Which carriers must the first release cover? → A: Four: Canada Post, Royal Mail, La Poste and USPS.
- Q: For a shop that already exists, is the catalogue and postage added automatically on upgrade, or only when the operator asks? → A: Automatically, when the release is deployed, for every existing shop.
- Q: When several postage services fit a parcel, which one does the margin use? → A: The shop's default service (the cheapest fitting one if none is set), which a product can override.
- Q: An existing shop has no country recorded; how is its carrier chosen for the automatic postage? → A: From its currency, for every currency in the catalogue: CAD → Canada Post, GBP → Royal Mail, USD → USPS, EUR → La Poste.
- Q: Should a shop be able to record its country, and does it choose the carrier? → A: Yes. The country is set like the currency (general settings and onboarding) and is optional; when it is set it chooses the carrier (CA → Canada Post, GB → Royal Mail, US → USPS, FR → La Poste), otherwise the currency does.

**Input**: User description: "Packaging page, with standard boxes, mailers and postage seeded by default." Full prompt: `specs/backlog.md`, section "Packaging page, with standard boxes and postage seeded by default". Raised from bugcap #44 and #59: operators cannot find where to define the boxes their products ship in, and a new shop must type every box size and postage bracket before its first margin is right.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find and manage packaging on its own page (Priority: P1)

An operator wants to record the boxes, mailers and void fill they ship in. They
open "Packaging" from the main navigation and see only packaging: each box and
mailer with its inner size, wall thickness, empty weight, stock and cost per
unit, each void fill or wrap with the volume one unit fills, and which products
use each item. "Add box", "Add mailer" and "Add void fill" open a form that asks
only for packaging figures and cost. Magnets, inserts and hardware stay on the
Consumables page, which no longer lists packaging.

**Why this priority**: Packaging already exists in the data, but operators do
not find it (bugcap #44, #59). Without packaging, the packaging advisor cannot
suggest a box and postage cannot be estimated from the packed parcel. This story
alone fixes that, even with an empty catalogue.

**Independent Test**: Open Packaging from the navigation, add a box with its
inner size and empty weight, then open a product whose dimensions fit it and see
the box suggested; open Consumables and confirm the box is not listed there.

**Acceptance Scenarios**:

1. **Given** a 3D-print shop, **When** the operator looks at the main navigation, **Then** a "Packaging" entry is shown next to Consumables.
2. **Given** the shop has two boxes, one void fill and three magnets, **When** the operator opens Packaging, **Then** exactly the two boxes and the void fill are listed, and **When** they open Consumables, **Then** only the three magnets are listed.
3. **Given** the operator chooses "Add box", **When** the form opens, **Then** the kind is already "Box" and the form asks for name, inner length, width and height, wall thickness, empty weight, cost per unit and stock, and nothing that only applies to hardware.
4. **Given** a box saved without inner dimensions, **When** it is listed, **Then** it is marked incomplete and the operator is told the advisor cannot use it until its size is entered.
5. **Given** a product for which no packaging fits, **When** the operator views its packaging card, **Then** it offers a link to the Packaging page.
6. **Given** a packaging item already used by products, **When** the operator tries to delete it, **Then** they are told which products use it, as for any consumable today.

---

### User Story 2 - Start with a standard packaging catalogue (Priority: P2)

A new shop finishes onboarding and opens Packaging: it already holds a set of
common shipping containers — corrugated boxes from small to large in cube and
flat shapes, padded and cardboard mailers, and void fill (paper, air pillows,
bubble wrap) — each with its inner size, wall and empty weight. Every catalogue
figure is shown as a default ("assumed") until the operator confirms or edits
it. A shop that already exists receives the same catalogue automatically when the
release is deployed; anything it already has is left as it is.

**Why this priority**: It removes the data entry that stops operators from
using the advisor at all, but it only helps once Story 1 makes packaging
visible.

**Independent Test**: Create a new 3D-print shop, keep the default catalogue
during onboarding, open Packaging and see the catalogue items with "default"
labels; open a product with dimensions and see a catalogue box suggested.

**Acceptance Scenarios**:

1. **Given** a new shop in onboarding, **When** the operator reaches the packaging step, **Then** the catalogue is listed with every item selected, and they can deselect items before continuing.
2. **Given** onboarding completed with the default selection, **When** the operator opens Packaging, **Then** every selected catalogue item is present with its dimensions, wall and empty weight, each labelled as a default (assumed) figure.
3. **Given** a catalogue box, **When** the operator edits its inner size and saves, **Then** that figure is recorded as entered by the operator and is no longer labelled as a default.
4. **Given** an existing shop that already has a box named like a catalogue box, **When** the release is deployed, **Then** the catalogue is added to the shop, the existing box is left untouched, no duplicate is created, and the Packaging page tells the operator which catalogue items were added and which were skipped and why.
5. **Given** the catalogue was added once, **When** the operator adds it again, **Then** nothing changes and the screen says every item is already present.
6. **Given** a margin built on a catalogue item whose cost is still a default, **When** the operator views that margin, **Then** it says the packaging cost is assumed, in the same way other assumed inputs are flagged.

---

### User Story 3 - Start with postage for the shop's carrier (Priority: P3)

During onboarding the operator picks the carrier and services they post with —
for example Canada Post (Lettermail, Small Packet, Expedited Parcel) or Royal
Mail (Large Letter, Small Parcel, Medium Parcel). The shop starts with postage
for those services: destination zones, weight brackets, size limits and the
carrier's published price in the shop's currency, each dated and labelled with
its source. The default packaging is checked against the services' size limits,
so the advisor and postage agree on which service a parcel fits.

**Why this priority**: Postage is the largest per-order cost after the item
itself, and a margin without it is wrong. It depends on Stories 1 and 2 for the
size check, and its data (tariffs) needs the most care.

**Independent Test**: Create a shop in the carrier's country, choose two
services in onboarding, then open Settings → Postage and see dated profiles for
those services; price a product whose packed parcel fits the smaller service
and see that postage used.

**Acceptance Scenarios**:

1. **Given** a shop whose country is covered by the catalogue (or, with no country recorded, whose currency is), **When** the operator reaches the postage step, **Then** the carrier for that country (or currency) is proposed with its services, and the operator chooses which to keep.
2. **Given** services chosen, **When** onboarding completes, **Then** Settings → Postage lists one profile per service, zone and weight bracket, with size limits, the price in the shop's currency, the tariff's effective date and its source, each labelled as a default.
3. **Given** a shop whose default service is Small Packet and a product that fits it, **When** the operator views the product's margin, **Then** the postage is the Small Packet price; **When** they override the product to Expedited Parcel, **Then** the margin uses Expedited Parcel.
4. **Given** a catalogue box larger than a service's size limits, **When** postage is estimated for a parcel in that box, **Then** that service is not offered for it, and the Packaging page notes which services each box fits.
5. **Given** the carrier publishes a new tariff and the catalogue is updated, **When** the operator next opens Postage, **Then** the new tariff is offered as a new dated set to accept, the current profiles are unchanged until they accept, and orders already placed keep the postage they were costed at.
6. **Given** a shop whose country or carrier is not in the catalogue, **When** it reaches the postage step, **Then** no postage is created, the operator is told so, and they are pointed to Settings → Postage to enter their own.
7. **Given** the shop already has postage profiles, **When** carrier postage is added (at release or by the operator), **Then** a profile that would overlap an existing one for the same zone and weight is not created, and the operator is told which were skipped.

---

### Edge Cases

- A EUR shop with no country recorded receives La Poste postage at release (carrier chosen from currency); the postage notice names La Poste and offers to switch carrier, and the switch supersedes the seeded profiles rather than editing them.
- A shop whose currency has no catalogue carrier (e.g. AUD) and no country recorded receives no postage and is told why.
- A shop whose country has no catalogue carrier (e.g. Belgium) receives no postage, even if its currency has one, and is told why; it can still choose a catalogue carrier priced in its currency by hand.
- A shop whose country's carrier is priced in another currency than its books (e.g. country Canada, books in USD) receives no postage and is told the carrier's currency differs.
- The operator records or changes the country after postage was seeded: nothing is re-seeded; Settings → Postage proposes the carrier for the new country, and switching supersedes the seeded profiles (FR-022).
- A catalogue item's name is already used by an item the operator created by hand: the operator's item is kept, the catalogue item is skipped and reported.
- The operator deletes a seeded catalogue item: adding the catalogue again restores it; the operator is told it was previously removed and can deselect it.
- Seeding fails part-way (catalogue data unreadable): the shop is still created, nothing partial is left for the failed part, and the operator sees which part was not seeded and how to add it later.
- A product already has accepted packaging that is not from the catalogue: seeding never changes a product's accepted packaging.
- Void fill and wrap have no inner size: they are complete with their fill volume only, and are never offered as the outer container.
- A shop that is not a 3D-print shop (knitting, generic): Packaging is available if its Consumables module is enabled; the catalogue is offered the same way.
- A viewer (read-only role) opens Packaging: they see the list but cannot add, edit, delete or seed.

## Requirements *(mandatory)*

### Functional Requirements

**Packaging page**

- **FR-001**: The system MUST provide a Packaging page reachable from the main navigation for every shop whose consumables module is enabled.
- **FR-002**: The Packaging page MUST list only items that have a packaging kind (box, mailer, void fill, wrap); the Consumables page MUST NOT list them.
- **FR-003**: For a box or mailer the list MUST show name, inner length × width × height, wall thickness, empty weight, stock, cost per unit, the products that use it and, once Story 3 is delivered, the postage services it fits; for void fill and wrap it MUST show the volume one unit fills instead of a size.
- **FR-004**: The Packaging page MUST offer "Add box", "Add mailer", "Add void fill" and "Add wrap", each opening a form already set to that kind and asking only for the fields that apply to it plus name, cost and stock.
- **FR-005**: Editing and deleting packaging MUST behave as it does for consumables today, including the refusal to delete an item in use, with the products named.
- **FR-006**: A box or mailer without inner dimensions MUST be shown as incomplete with the reason, and MUST NOT be offered by the packaging advisor.
- **FR-007**: A product's packaging card MUST link to the Packaging page when no packaging fits it.
- **FR-008**: Only roles that may change operational figures MUST be able to add, edit, delete or seed packaging; other roles see the page read-only.

**Default packaging catalogue**

- **FR-009**: The system MUST hold a standard packaging catalogue of at least 8 boxes (cube and flat shapes, small to large), 3 mailers and 3 void fill or wrap items, each with the figures FR-003 lists for its kind.
- **FR-010**: Onboarding of a new shop MUST include a packaging step listing the catalogue with every item selected by default; the selected items MUST be created for the shop when onboarding completes.
- **FR-011**: Every shop that exists when the release is deployed MUST receive the catalogue automatically, under the same rules as FR-012; the Packaging page MUST tell the operator, once, what was added and what was skipped, and MUST also let the operator re-add catalogue items later (for example after deleting one).
- **FR-012**: Adding the catalogue MUST be idempotent: an item already present (by catalogue identity, or by an operator item of the same name and kind) MUST NOT be created again, and an item the operator has edited MUST NOT be changed; skipped items MUST be reported with the reason.
- **FR-013**: Every figure created from the catalogue MUST carry the provenance "assumed" (a catalogue default) and be shown as such; an operator edit MUST change that figure's provenance to the operator's, and MUST NOT relabel the other figures.
- **FR-014**: Every catalogue box, mailer, void fill and wrap MUST come with a typical purchase cost per unit in the shop's currency, with provenance "assumed"; any margin that uses an assumed packaging cost MUST say so until the operator confirms or replaces the cost. A shop whose currency has no typical cost in the catalogue gets the item without a cost, and its margins say the packaging cost is missing.
- **FR-015**: Seeding MUST NOT prevent a shop from being created: a catalogue failure MUST be reported to the operator, and nothing partial MUST remain for the part that failed.

**Default postage**

- **FR-016**: The system MUST hold a postage catalogue per supported carrier, listing its services and, for each service, destination zones, weight brackets, size limits, volumetric divisor where the carrier uses one, price, currency, tariff effective date and source. The first release MUST cover four carriers: Canada Post (Lettermail, Small Packet, Expedited Parcel), Royal Mail (Large Letter, Small Parcel, Medium Parcel), La Poste (Lettre suivie, Colissimo) and USPS (Ground Advantage, Priority Mail).
- **FR-017**: Onboarding MUST include a postage step that proposes the carrier for the shop's country, or for its currency when no country is recorded (the maps of FR-018), and lets the operator choose services; when onboarding completes, a postage profile MUST be created for each chosen service, zone and weight bracket.
- **FR-017a**: A shop MUST be able to record its country (optional, one ISO country) in general settings and in onboarding, alongside its currency. Existing shops have none until the operator sets one.
- **FR-018**: Every shop that exists when the release is deployed MUST receive carrier postage automatically for the carrier matching its country when one is recorded (CA → Canada Post, GB → Royal Mail, US → USPS, FR → La Poste), otherwise its currency (CAD → Canada Post, GBP → Royal Mail, USD → USPS, EUR → La Poste), with all of that carrier's catalogue services, without creating a profile that overlaps an existing one for the same zone, weight and dates; Settings → Postage MUST tell the operator, once, what was added and what was skipped, and MUST let the operator add or remove services later.
- **FR-018a**: Because this automatic addition can change the postage, and so the margin, of products that had no matching postage before, the release MUST produce, before it is applied to a shop, a per-product report of the margins that change and by how much.
- **FR-019**: Seeded postage profiles MUST carry the provenance "assumed", the tariff's effective date and its source, and be shown as defaults until the operator confirms or edits them.
- **FR-020**: A newer carrier tariff in the catalogue MUST be offered to the shop as a new effective-dated set; the shop's current profiles MUST NOT change until the operator accepts, and accepting MUST supersede rather than edit the current ones.
- **FR-021**: Orders already placed MUST keep the postage they were costed at, whatever the catalogue or the shop's profiles later become.
- **FR-022**: When the shop's country (or, with no country, its currency) has no catalogue carrier, or that carrier is priced in another currency than the shop's, the system MUST create no postage and MUST tell the operator why and where to enter postage by hand. The postage notice MUST name the carrier and say whether it was chosen from the country or the currency, and let the operator replace it with another catalogue carrier (for example a EUR shop outside France), which supersedes the seeded profiles.
- **FR-023**: Postage estimation MUST NOT offer a service for a parcel whose packed size exceeds that service's size limits; the Packaging page MUST show, per box and mailer, which seeded services it fits.
- **FR-023a**: A shop MUST be able to choose a default postage service; when it has none, the default is the cheapest service the parcel fits. A product MUST be able to override the default with another service it fits. The margin MUST use the product's service, else the shop's default; when the chosen service does not fit the parcel, the margin MUST fall back to the cheapest fitting service and say so.

**General**

- **FR-024**: Every item and profile created by this feature MUST belong to the shop that created it and MUST NOT be visible to any other shop.
- **FR-025**: Existing packaging items and postage profiles MUST keep working unchanged and appear on the new Packaging page and in Postage without any action from the operator.

### Key Entities

- **Shop**: existing entity; gains an optional country, recorded like its currency, used to choose the carrier.
- **Packaging item**: a consumable the shop buys and uses up to ship orders — a box, mailer, void fill or wrap. Has a name, a kind, inner size (box, mailer), wall thickness, empty weight, fill volume (void fill, wrap), cost per unit, stock and, per figure, where it came from (catalogue default, entered, measured). Optionally linked to the catalogue entry it came from.
- **Packaging catalogue entry**: a standard container the product ships with — name, kind, figures and, optionally, a typical cost. Shared reference data, identical for every shop, versioned so a later catalogue change can be told apart.
- **Postage profile**: what the shop pays to send a parcel of a given weight and size to a zone with a given service, effective from a date. Existing entity; gains a source and provenance when created from the catalogue.
- **Carrier tariff catalogue entry**: a carrier's published service — zones, weight brackets, size limits, volumetric divisor, price, currency, effective date and source. Shared reference data, versioned by effective date.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator who has never used Packaging can find it and add a box in under 2 minutes, without help.
- **SC-002**: A new shop that keeps the defaults has at least 8 boxes, 3 mailers and 3 void fill or wrap items, and (for a supported carrier) postage for every chosen service, immediately after onboarding, with zero figures typed by the operator.
- **SC-003**: For a product with dimensions, the packaging advisor suggests a container on the first visit after onboarding in at least 90% of cases where any catalogue box fits.
- **SC-004**: Adding the catalogue twice to the same shop creates no duplicate items and changes no operator-edited figure (0 duplicates, 0 overwritten edits).
- **SC-005**: 100% of seeded figures are visibly labelled as defaults until confirmed or edited.
- **SC-006**: No placed order's postage changes when a new carrier tariff is accepted (0 restated orders).
- **SC-007**: Support questions of the form "where do I add my boxes?" (bugcap #44-type reports) stop recurring after release.

## Assumptions

- Packaging stays a kind of consumable: the Packaging page is a dedicated view of the existing consumable records, not a separate inventory. The Consumables page keeps hardware.
- Catalogue figures (sizes, wall thickness, empty weights) are typical values for common corrugated boxes and mailers used by small makers; they are good enough to start and are labelled as defaults so operators replace them with their own.
- A shop's country only chooses the carrier; it does not change prices, zones or currency, and changing it re-seeds nothing.
- Carrier prices are not converted between currencies; a carrier is offered only to shops priced in that carrier's currency.
- Carrier tariffs in the catalogue are maintained by Batchivo releases (a new tariff arrives with an update), not fetched live from carriers.
- The default zone set per carrier is domestic plus the carrier's main international zones; regional surcharges (remote areas) are out of scope for the first release.
- Onboarding steps are skippable: an operator who skips them can add the catalogue and postage later from the Packaging page and Settings → Postage.
- Shops that exist at release time are seeded once, automatically; a later catalogue version is not re-applied automatically (a new tariff follows FR-020).
- The packaging advisor, postage estimation and parcel confirmation (feature 003) are reused unchanged, apart from the size-limit check of FR-023.
- Who may change packaging follows the existing rule for operational figures (member, admin or owner); viewers read only.
