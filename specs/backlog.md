# Backlog

Features waiting for a spec. Each entry is the prompt to pass to `/speckit-specify`.

---

## Model file versions, a measurable source file, a 3D viewer and pinned notes

**Status:** specified in `specs/004-model-file-versions/spec.md`

**Why:** a Bambu Studio `.gcode.3mf` is a sliced plate, so it carries no mesh and
the upload is reported as "The 3MF build has no geometry". The model then has no
dimensions for the packaging advisor or postage. Operators also iterate on a
design and need to keep earlier versions without losing which one is printed.

**What already exists (do not rebuild):**
- `ModelFile` (`backend/app/models/model_file.py`) already allows many files per
  model, with `file_type`, `version`, `notes`, `is_primary` (unique per model and
  file type, `model_file_service.py:786`) and the measurement columns.
- `mesh_bounds.measure` measures STL and mesh-bearing 3MF files;
  `item_dimensions.apply_measurement` writes a measurement to the model only when
  it has no dimensions yet or the operator adopts it, never over an entry.
- `ModelForm.tsx` has "Auto-fill from .3mf file", which parses print time, plate
  count and filament weight but does not keep the file.
- `ModelFilesEditor.tsx` on the edit page uploads and stars files.

### Prompt

```text
/speckit-specify Model file versions and a measurable source file.

Context: in Batchivo a model (a printable item) can have files attached
(ModelFile: file_type, version, notes, is_primary, measured_* columns). A
Bambu Studio sliced export (.gcode.3mf) holds G-code and thumbnails but no mesh,
so measuring it fails with "The 3MF build has no geometry" and the model gets no
dimensions for the packaging advisor and postage. Operators also revise their
designs and want to keep every version.

1. Measurable source file on create and edit
   - On both the create and the edit model screens, the operator can attach a
     source file: an .stl or a project .3mf that contains a mesh (not a
     .gcode.3mf). It is stored as a model file and measured to estimate the
     model's dimensions.
   - The existing "Auto-fill from .3mf" step stays; a file chosen there can also
     be kept as a model file instead of being discarded after parsing.
   - When a file has no geometry (a sliced .gcode.3mf), the screen says so in
     plain words and tells the operator what to upload instead (the project .3mf
     from "Save project", or the .stl), rather than only showing the parser
     error.
   - A measurement never overwrites dimensions the operator entered; it is
     offered for adoption, as today.

2. Several files per model, with versions and one active file
   - A model can hold any number of files, sliced (.gcode, .gcode.3mf) and
     unsliced (.stl, .3mf) alike, each with a version label and a short note on
     what changed ("thicker walls", "fixed overhang on the handle").
   - The operator marks which version is active. The active version is the one
     used for the final print: its print time, plate count and filament weight
     feed the cost profile, and its mesh (or, if it has none, the newest
     measurable file of the same version) gives the dimensions.
   - Older versions stay listed, newest first, with their note, upload date and
     who uploaded them, and can be downloaded or made active again.
   - Changing the active version does not silently move recorded figures:
     the operator sees which cost-profile and dimension values would change and
     chooses which to apply, the same way the 3MF auto-fill works today.
   - Deleting the active file is refused until another version is made active.

3. 3D viewer to check an uploaded file
   - Every model file can be opened in an in-browser 3D viewer: a mesh
     (.stl, project .3mf) as a solid, a sliced file (.gcode, .gcode.3mf) as its
     toolpaths with a layer slider.
   - A .gcode.3mf is read by extracting its plate G-code (Metadata/plate_N.gcode)
     in the browser; a multi-plate file lets the operator pick the plate.
   - The viewer shows the planned printer's bed outline (e.g. 256 x 256 mm for an
     A1) so a part off the bed or oversized is visible, and states what the
     G-code header says it was sliced for (printer, filament, nozzle) when that
     differs from the model's planned machine.
   - Large files stay usable: parsing runs off the main thread, and above a size
     limit the viewer shows a reduced preview and says so, rather than freezing.

4. Notes pinned on the part, carried across versions
   - In the viewer the operator clicks a point on the part (or a layer of the
     toolpaths) and leaves a note there, shown as a numbered pin with a tooltip
     that stays attached to that point as the view rotates.
   - A note records its file, the 3D point and surface normal, the layer when it
     was placed on G-code, its text, author and date, and a status: open, or
     resolved in version N.
   - Opening a newer version shows the previous version's open notes as ghost
     pins at the same coordinates, so the operator can mark each one resolved or
     carry it forward. That is the place to leave "next version" notes.
   - Notes are listed beside the viewer too, so they can be read and filtered
     without the 3D view (e.g. on a phone).

Suggested tooling (decide in the plan): three.js with @react-three/fiber v9
(React 19) and @react-three/drei (camera controls, <Html> tooltips); three's
STLLoader and 3MFLoader for meshes; gcode-preview for toolpaths; fflate or JSZip
to unzip a .gcode.3mf; a Web Worker for parsing.

Constraints:
- Reuse ModelFile and its existing version, notes and is_primary columns
  rather than adding a parallel table; decide in the plan whether "active" is
  is_primary per model, or a version grouping of a sliced file and its source.
- Every file stays tenant-scoped (tenant_id, RLS) like the rest of ModelFile.
- Figures applied from a file keep their provenance (measured from the file),
  following the pricing constitution: nothing derived is stored, and a past
  order's cost does not move because the active version changed.
- No breaking change to the existing model-files API; existing files become
  version "1" with the current primary file active.
- Pinned notes are a new tenant-scoped table (tenant_id, RLS) tied to a model
  file; deleting a file keeps or archives its notes, never silently drops the
  open ones of the active line.
- The viewer is a lazy-loaded chunk so the three.js bundle does not weigh on
  other pages.
- Tests for each new endpoint (200/201, 401, 404, 422) and for the
  no-geometry, version-switch, delete-active, note carry-over and
  oversized-file cases.
```

---

## Single-tenant VPS edition: one installed instance per shop

**Status:** specified in `specs/005-single-tenant-vps/spec.md`

**Why:** the business model is to sell each 3D-print shop owner its own Batchivo,
installed on a VPS, that grows with their needs. The code is multi-tenant but runs
for one business; the shop identity (Mystmere Forge) is written into the code
instead of coming from the tenant's settings, so a second customer would send its
buyers to Mystmere. The current account is **HandyLabs**, not Mystmere.

**What already exists (do not rebuild):**
- `Tenant` (name, slug, currency, `settings` JSONB, `tenant_type`), memberships and
  roles (`UserTenant`), team invites (`tenant_members.py`), modules per tenant.
- Onboarding wizard (`onboarding.py`, 4 steps + logo), tenant settings with shop
  URL slug and verified custom domain (`settings.py`, `tenant_settings.py`).
- Square and Resend configured per instance by environment (`config.py`).
- Platform admin console (`platform.py`, `is_platform_admin`), shop resolution by
  subdomain / path / custom domain (`shop_resolver.py`, `auth/dependencies.py`).
- `/register` already refuses sign-up (`auth.py`); `docker-compose.yml` runs only
  infrastructure (postgres, redis, observability), not the app.
- `LICENSE` is MIT, copyright Jonathan Gill.

### Prompt

```text
/speckit-specify Single-tenant VPS edition: one Batchivo instance per shop, behind a
deployment-mode flag, with the shop identity taken from the tenant's settings. The
licence stays MIT.

Context: Batchivo is multi-tenant in code (tenant_id on every table, RLS policies,
memberships, platform admin console, shop resolution by subdomain/path/custom
domain) but is sold and run as one business per installation. Each customer gets
its own VPS with its own database and its own Square / Resend credentials. The
current production account is HandyLabs; strings naming Mystmere Forge are
hard-coded across the backend and frontend.

1. Deployment mode flag
   - A setting DEPLOYMENT_MODE with two values: `single` (one tenant per
     installation) and `multi` (today's behaviour). Default `single`.
   - In `single`: exactly one active tenant; public registration closed; the
     platform admin console, tenant impersonation, tenant listing and the
     subdomain/path shop resolution are hidden in the UI and refuse access in the
     API (404 or 403, decided in the plan); the shop resolves to the one tenant
     (and its custom domain when set).
   - In `multi`: everything behaves as today. No multi-tenant code is deleted;
     it is gated by the flag so the SaaS model can be switched back on.
   - The frontend learns the mode from the backend (or runtime config), not from
     a build-time constant, so one image serves both modes.

2. Shop identity from the tenant, not from the code
   - Every customer-facing identity value comes from the tenant's settings or the
     instance configuration: shop name, shop website / base URL, order
     confirmation URL, product URLs, vendor name in exports and Shopify sync,
     Square order name / note / reference prefix, email sender and display name,
     social handle, the "shop is being upgraded" handover message, and the
     ProductForm label ("appears in the <shop name> shop").
   - Inventory every hard-coded "mystmere" / "Mystmere Forge" / mystmereforge.co.uk
     occurrence (payments.py, products.py, shop.py incl. the sitemap/base_url and
     seeded slug lists, commerce_handover.py, export_service.py, shopify_sync.py,
     square_payment.py, ProductForm.tsx, the k8s deployment env SHOP_NAME /
     SHOP_WEBSITE_URL / SHOP_SOCIAL_HANDLE) and replace each with the configured
     value. Docstring/example mentions are changed to a neutral example.
   - Stable identifiers that already exist in stored data (e.g. the
     `mystmere:{tenant.id}:woocommerce:...` UUID namespace in
     commerce_order_ownership.py, Square reference ids already sent) MUST NOT
     change for existing records: a changed namespace would mint new ids for
     known orders. Decide in the plan how to keep them stable (keep the legacy
     prefix as a constant, or derive from the tenant only for new records).
   - A missing identity value is a clear startup or onboarding error, never a
     silent fallback to another shop's name or URL.
   - The current production tenant is renamed/configured as HandyLabs through
     data (settings / migration or admin action), not through code.

3. Install, first run, update, backup
   - A production docker-compose bundle for one VPS: backend, frontend, postgres,
     redis and a reverse proxy with automatic HTTPS (Caddy). Observability
     (Tempo, Loki, Prometheus, Grafana) is an optional profile; Sentry stays
     available through its DSN.
   - Versioned images published to a registry reachable from customer VPSs.
   - A first-run command that runs migrations, creates the single tenant and its
     owner account, then hands over to the existing onboarding wizard.
   - An update command: back up the database, pull the pinned version, run
     `alembic upgrade head`, restart, and report the result; a failed migration
     leaves the backup and the previous version restorable.
   - A scheduled `pg_dump` backup with retention and an off-server target, plus a
     documented restore.
   - An `.env.example` listing every variable an instance needs, with which are
     required in `single` mode.

4. Licence
   - The licence stays MIT. The offer sells installation, hosting and support of
     instances; no licence change.

Constraints:
- No breaking change for the running HandyLabs instance: switching it to
  `single` mode keeps its data, URLs (from settings) and integrations working.
- Multi-tenant security rules still apply in both modes: every query is tenant
  scoped; RLS can be enabled per instance.
- Money rules from the pricing constitution are untouched.
- Tests: the flag in both modes (gated routes 403/404 in single, unchanged in
  multi; registration closed; shop resolution to the single tenant); every
  replaced identity value is read from settings (a test tenant with a different
  name and URL never yields "mystmere"); a guard test that greps the source for
  hard-coded shop identity; the stable-identifier case; first-run and update
  scripts on a throwaway database.
```

---

## Packaging page, with standard boxes and postage seeded by default

**Status:** specified in `specs/006-packaging-catalogue/spec.md`

**Why:** shipping boxes, mailers and void fill are modelled as consumables with a
`packaging_kind`, but the only place to create them is a "Packaging" section at the
bottom of the "Add consumable" dialog, on a page titled "Manage magnets, inserts,
hardware". Operators do not find it (bugcap #44, #59), so products get no packaging
and the packaging advisor and postage have nothing to work with. A new shop also
starts with no boxes and no postage at all: every dimension, empty weight and
carrier bracket has to be typed in before the first margin is right.

**What already exists (do not rebuild):**
- `ConsumableType` (`backend/app/models/consumable.py`): `packaging_kind`
  (box, mailer, void_fill, wrap), `inner_length/width/height_mm`, `wall_mm`,
  `empty_weight_grams`, `fill_volume_ml`, packaging provenance, cost per unit and
  purchases. Packaging UI: `components/inventory/PackagingFieldsSection.tsx`.
- Packaging advisor (`services/packaging_advisor.py`, `ProductPackagingCard`,
  `PackagingSuggestions`) picks a container from the product's dimensions.
- `ShippingProfile` (`models/shipping_profile.py`): postage by destination zone and
  weight bracket, carrier, size limits (`max_length/width/height_mm`), volumetric
  divisor, effective-dated (`effective_from/to`); managed in Settings → Postage
  (`ShippingProfilesPanel.tsx`). Orders freeze their postage (`freeze_order_postage`).
- The `consumables` module and nav entry (enabled for 3D-print tenants since
  commit 17aa9ca); onboarding wizard (`onboarding_service.py`,
  `onboarding_wizard.py`) with the tenant's currency and country.

### Prompt

```text
/speckit-specify Packaging page, with standard boxes, mailers and postage seeded
by default.

Context: in Batchivo a box, mailer, void fill or wrap is a ConsumableType with a
packaging_kind and its inner dimensions, wall, empty weight and fill volume. The
packaging advisor picks a container for a product from those figures, and
postage comes from ShippingProfile rows (zone, weight bracket, carrier, size
limits, volumetric divisor, effective-dated). Today packaging can only be created
from a section of the generic "Add consumable" dialog on the Consumables page
("magnets, inserts, hardware"), and a new shop starts with no packaging and no
postage, so operators must type every figure before any margin is right.

1. A dedicated Packaging page
   - A "Packaging" entry in the main navigation, separate from Consumables,
     listing only consumables that have a packaging_kind: boxes and mailers with
     their inner size, wall and empty weight; void fill and wrap with their fill
     volume. Stock, cost per unit and the products that use each one are shown.
   - "Add box / mailer / void fill" opens the existing consumable form already
     in packaging mode with the kind chosen, asking only the packaging fields and
     the cost; editing and deleting reuse the existing consumable endpoints.
   - The Consumables page no longer lists packaging (or offers a filter), and its
     wording stays "magnets, inserts, hardware".
   - From a product's packaging card, "no suitable packaging" links to this page.

2. A standard packaging catalogue, seeded by default
   - A tenant starts with a catalogue of common shipping containers so the
     advisor works on day one: a range of corrugated boxes (small to large cube
     and flat sizes typical for 3D-printed items), padded and cardboard mailers,
     and void fill (paper, air pillows, bubble wrap), each with inner dimensions,
     wall thickness and empty weight.
   - Seeded figures carry provenance `assumed` (a catalogue default), never
     `observed` or `measured`; the screen shows them as defaults until the
     operator confirms or edits them. A seeded item has no cost unless the
     catalogue states a typical one, also `assumed`, and the margin flags a cost
     built on an assumed packaging price.
   - The operator picks which catalogue items to keep (all by default) during
     onboarding, and can add the catalogue later from the Packaging page for an
     existing tenant; seeding is idempotent and never overwrites or duplicates an
     item the operator already has or has edited.
   - Sizes are expressed in mm and g; the catalogue is data (a versioned file or
     table), not values scattered in code.

3. Postage profiles seeded from the tenant's country and carrier
   - Onboarding asks (or infers from the tenant's country and currency) which
     carrier/service the shop uses, e.g. Canada Post (Lettermail, Small Packet,
     Expedited Parcel), Royal Mail (Large Letter, Small Parcel, Medium Parcel),
     La Poste (Lettre suivie, Colissimo), USPS (Ground Advantage, Priority Mail).
   - The chosen services seed ShippingProfile rows: zones (domestic and the
     carrier's main international zones), weight brackets, size limits and
     volumetric divisor per service, with the published postage in the tenant's
     currency, effective from the carrier's tariff date and labelled with its
     source and that date. Provenance `assumed` until the operator confirms.
   - The seeded catalogue's boxes are checked against each service's size
     limits, so the advisor and postage agree on which service a parcel fits.
   - Seeded postage is never updated in place: a new carrier tariff is offered as
     a new effective-dated set the operator accepts (supersede, never update),
     and a placed order keeps the postage it was costed at.
   - A shop whose carrier is not in the catalogue gets no postage seeded and is
     told so, with a link to Settings → Postage.

Constraints:
- No new parallel packaging table: reuse ConsumableType (packaging_kind and its
  columns) and ShippingProfile; every seeded row is tenant-scoped (tenant_id, RLS).
- Pricing constitution: Decimal end to end, decimal strings on the wire; every
  seeded input states its provenance; history is effective-dated; nothing
  derived is stored.
- Seeding must not fail onboarding: a catalogue error is reported and the tenant
  is still created.
- No breaking change to the consumables and shipping-profiles APIs; existing
  packaging consumables appear on the new page unchanged.
- Tests: Packaging page lists only packaging and creates in packaging mode;
  Consumables page excludes it; seeding creates the catalogue for a new tenant,
  is idempotent, never overwrites an edited item; seeded rows are `assumed`;
  postage seeding per carrier, size-limit consistency with the boxes, unknown
  carrier seeds nothing; new endpoints 200/201, 401, 404, 422.
```
