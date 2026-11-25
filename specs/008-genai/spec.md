# Feature Specification: Generative AI layer, Replicate first

**Feature Branch**: `claude/elastic-clarke-98bb9f` (spec 008)

**Created**: 2026-11-24

**Status**: Draft

**Input**: User description: the "Generative AI layer with Replicate" block of `specs/backlog.md`
(feature 008), architecture in `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §5:

> Generative AI layer with Replicate as the first provider. Batchivo (3D printing business
> management) has no AI integration. The operator wants to use generative models hosted on
> Replicate wherever they help: drafting a product image from an idea, improving product photos,
> producing sales images, and drafting a 3D shape from an image.
> 1. Capabilities, not model names. 2. Generation jobs. 3. Where it appears (Ideas, Products,
> Models; adoption is explicit). 4. Credentials, cost and safety.
> Constraints: provider-agnostic service with a Replicate adapter; cost computed in one service;
> money is Decimal, decimal strings on the wire; a job's inputs, model version and seed are written
> once; tenant-scoped tables with RLS; the provider token never reaches the frontend or logs; the
> Replicate HTTP API is mocked in tests.

## Clarifications

### Session 2026-11-24

- Q: In which currency are the monthly AI budget and each generation's cost entered and shown? → A: US dollars everywhere (budget, cost per job, month-to-date usage); no FX conversion.
- Q: When a shop has no Replicate token of its own, may the platform token be used for every shop or only for authorised ones? → A: Only for shops a platform admin authorises one by one (switch on the shop's platform-admin page, off by default); on a single-shop VPS install the only shop is authorised automatically.
- Q: Who in a shop may start, cancel and adopt a paid AI generation? → A: Owner, admin and member (within the budget and concurrency limit); viewers can only look. Replicate settings stay owner/admin only.
- Q: What does a 3D draft adopted on an idea become? → A: A generation timeline entry shown in the existing 3D viewer with a download button; when the idea is converted into a model (or a product with its model), every adopted 3D draft becomes a file version of the new model labelled "AI draft", never the active one.
- Q: May provider-maintained ("official") Replicate models, which cannot be pinned to a version, be used? → A: Yes. Each job records the version the provider actually ran (visible, never changed); community models stay pinned.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect Replicate and control spending (Priority: P1)

The operator opens Settings → Integrations → Replicate, pastes an API token, tests the connection,
sets a monthly budget and sees how much has been spent this month. Without this nothing else can
run, and without the budget nothing else is safe to run.

**Why this priority**: every other story needs a working provider connection and a spending cap.

**Independent Test**: save a token, run the connection test against a mocked provider, set a
budget, and read back a masked token and a month-to-date usage of zero.

**Acceptance Scenarios**:

1. **Given** no Replicate token is configured, **When** the operator saves a token, **Then** the
   token is stored encrypted, the page shows it masked (only its last 4 characters), and it never
   appears in any response, page or log.
2. **Given** a saved token, **When** the operator clicks "Test connection", **Then** the page shows
   whether the provider accepted the token (and the account name when it did).
3. **Given** a monthly budget of 10.00, **When** the operator opens the page, **Then** it shows the
   budget, the month-to-date spend and the number of jobs this month.
4. **Given** the tenant has no token, the platform has one configured and a platform admin has
   authorised this tenant to use it, **When** a job is requested, **Then** the platform token is
   used and the settings page says so. **Given** the same but the tenant is not authorised,
   **Then** AI actions say Replicate is not connected.
5. **Given** neither a tenant nor a platform token, **When** the operator opens any AI action,
   **Then** the action explains that Replicate is not connected and links to the settings page.
6. **Given** the settings page, **When** the operator overrides the model for a capability (model
   reference plus pinned version), **Then** later jobs of that capability use the override, and
   clearing it returns to the built-in default.

---

### User Story 2 - Generate a concept image from an idea (Priority: P1)

On an idea's page the operator clicks "Generate concept". The dialog pre-fills a prompt from the
idea's title and summary, lets the operator pick reference images from the idea's timeline and a
number of images, shows an estimated cost, and starts the job. The dialog shows progress, then a
grid of results; each result the operator adopts becomes a timeline entry of kind generation.

**Why this priority**: Ideas is the first consumer named by the architecture and exercises the
whole job pipeline (validation, budget, background run, storage, adoption).

**Independent Test**: with the provider mocked, start a concept job on an idea, let it succeed,
adopt one output, and see a generation entry on the idea's timeline linked to the job.

**Acceptance Scenarios**:

1. **Given** an idea with a title and summary, **When** the operator opens "Generate concept",
   **Then** the prompt is pre-filled from the idea and the estimated cost is shown before starting.
2. **Given** a started job, **When** the provider is still working, **Then** the dialog shows the
   job as queued, then running, without the operator reloading the page.
3. **Given** a job that succeeded, **When** the results arrive, **Then** each output is already
   stored in Batchivo (it remains viewable after the provider deletes its copy) and shown in a grid.
4. **Given** a result, **When** the operator clicks "Adopt", **Then** a timeline entry of kind
   generation appears in the idea's current iteration, carrying the image and a link to the job
   (capability, prompt, model and version, seed); results not adopted stay in the job only.
5. **Given** an image on the idea's timeline, **When** the operator chooses "Edit with AI" or
   "Variations", **Then** an image-edit job starts from that image with the operator's instruction.
6. **Given** an image on the idea's timeline, **When** the operator chooses "Draft 3D shape",
   **Then** an image-to-3D job starts; its mesh result can be adopted as a generation entry that
   shows the mesh in the 3D viewer and offers it for download, labelled as an AI draft.
7. **Given** an idea with adopted 3D drafts, **When** it is converted into a model (or a product
   and its model), **Then** each adopted draft becomes a file version of the new model labelled
   "AI draft", and none of them is the active version.

---

### User Story 3 - Improve product photos and make sales images (Priority: P2)

In a product's image editor the operator selects a product photo and chooses enhance, remove
background, upscale, or "Lifestyle scene" (with a scene description). Results appear next to the
original; the operator adopts one as a new product image. Every product image shows its origin
(photo, render of the real geometry, or AI), AI images carry a badge, and adopting an image that
does not show the real item (a concept image or a 3D draft) shows a warning first.

**Why this priority**: sales images are the most frequent use once the pipeline exists, but they
depend on story 1 and reuse the job pipeline proven in story 2.

**Independent Test**: on a product with one photo, run "Remove background" (mocked), adopt the
result, and see a new product image with the AI badge while the original is unchanged.

**Acceptance Scenarios**:

1. **Given** a product photo, **When** the operator runs enhance, remove background, upscale or
   lifestyle scene, **Then** a job starts from that photo and its results appear when done.
2. **Given** a result, **When** the operator adopts it, **Then** it is added as a new product image
   with origin "AI" and the AI badge; the source photo is not replaced or modified.
3. **Given** existing product images uploaded before this feature, **When** the editor loads,
   **Then** they show origin "photo"; the operator can change an image's origin between photo and
   render.
4. **Given** a concept image or an image-to-3D output, **When** the operator tries to adopt it as a
   product image, **Then** a warning states that listings must show the real item, and the image is
   added only after the operator confirms.
5. **Given** any AI image among a product's images, **When** it is shown in the editor, **Then** it
   carries an "AI" badge.

---

### User Story 4 - Draft a 3D model file from an image (Priority: P3)

On a model's page the operator clicks "Draft 3D from image", picks or uploads an image, and starts
an image-to-3D job. The resulting mesh, once adopted, becomes a new model file version labelled as
an AI draft; it never becomes the primary or active version on its own.

**Why this priority**: useful but slower and costlier; it depends on stories 1 and 2.

**Independent Test**: on a model, run a mocked image-to-3D job, adopt the mesh, and see a new file
version labelled "AI draft" while the active version is unchanged.

**Acceptance Scenarios**:

1. **Given** a model, **When** the operator runs "Draft 3D from image", **Then** a job starts with
   the chosen image.
2. **Given** a succeeded job, **When** the operator adopts the mesh, **Then** it is added as a new
   model file version labelled as an AI draft, viewable in the 3D viewer; the currently
   active/primary version and the model's dimensions are unchanged.

---

### User Story 5 - Follow, cancel and audit generation jobs (Priority: P3)

The operator (and, later, an AI agent) can list generation jobs with their status, cost and target,
open one to see exactly how it was made, cancel a queued or running job, and see failures with a
readable reason.

**Why this priority**: needed for trust and cost control, and the base that feature 010 (MCP
server) exposes to agents.

**Independent Test**: create jobs in several states (mocked provider), list them filtered by
target, cancel a running one, and read a failed one's error.

**Acceptance Scenarios**:

1. **Given** several jobs, **When** the operator lists jobs for a target (an idea, a product or a
   model), **Then** only that target's jobs appear, newest first, with status, capability and cost.
2. **Given** a queued or running job, **When** the operator cancels it, **Then** it is canceled at
   the provider (when submitted) and its status becomes canceled.
3. **Given** a job the provider failed, or one that ran past the time limit, **When** the operator
   opens it, **Then** it shows status failed and a readable reason, and no output is offered.
4. **Given** any job, **When** it is read, **Then** it shows its capability, provider, model and
   pinned version, inputs (prompt, parameters, seed, input images), target, who asked, timings and
   cost — and none of these inputs ever change after creation.

---

### Edge Cases

- **Budget reached**: a job whose estimated cost would take month-to-date spend over the budget is
  refused before anything is sent to the provider, with a message naming the budget and the spend.
- **Concurrency limit**: a tenant already running the maximum number of jobs gets a clear refusal
  (try again when one finishes); nothing is queued silently.
- **Provider unreachable or erroring**: submission errors and provider failures end the job as
  failed with the reason; transient errors are retried a bounded number of times first.
- **Timeout**: a job not finished within the capability's time limit is canceled at the provider
  and marked failed ("timed out").
- **Results expire at the provider**: outputs are copied into Batchivo storage as soon as the job
  succeeds; if the copy fails, the job is failed with that reason rather than left "succeeded" with
  missing results.
- **Webhook and polling race**: the job completes once, whichever path reports first; a duplicate
  or late report changes nothing.
- **Invalid webhook signature, stale timestamp, or unknown prediction**: rejected without changing
  any job.
- **Invalid inputs**: a missing prompt, an image the tenant does not own, an unsupported image type,
  too many images or an out-of-range count/factor are refused before any cost is incurred.
- **Target deleted or archived meanwhile**: the job still completes and stays readable; adoption
  into a missing target is refused.
- **Override pointing at a model that no longer exists**: the job fails with the provider's reason;
  the settings page lets the operator clear the override.
- **Token revoked at the provider**: jobs fail with an authentication reason; the connection test
  reports it.
- **Adopting the same output twice into the same target**: refused (already adopted); adopting an
  output into its target records where it went.
- **Cost unknown**: when the provider does not report a cost, the job records the estimated cost
  with its provenance marked as estimated.

## Requirements *(mandatory)*

### Functional Requirements

**Capabilities**

- **FR-001**: The system MUST offer these capabilities, each with its own validated inputs:
  concept image (prompt, optional reference images, optional style, image count), image edit (one
  image and an instruction), product photo enhancement (one image), background removal (one
  image), upscaling (one image and a factor), lifestyle scene (one product image and a scene
  description), and image to 3D (one or more images, producing a mesh).
- **FR-002**: Each capability MUST map to a provider, a model and default parameters. A community
  model MUST be pinned to an exact version, never "latest". A provider-maintained ("official")
  model, which cannot be pinned, MAY be used; each job then MUST record the exact version the
  provider reports it ran, written once and visible on the job.
- **FR-003**: The operator MUST be able to override, per capability, the model and pinned version
  used for their tenant, and clear the override.
- **FR-004**: Screens and agents MUST ask for a capability, never a model; adding a second provider
  later MUST NOT require changing screens.
- **FR-005**: The list of capabilities, with their inputs, limits and the model each will use for
  the tenant, MUST be readable by the frontend and by non-HTTP callers (feature 010).

**Generation jobs**

- **FR-006**: Every request MUST create a generation job recording: capability, provider, model and
  pinned version, inputs (prompt, parameters, seed, input images), target (idea, product, model or
  none), status (queued, running, succeeded, failed, canceled), error, timings, cost with its
  provenance (provider-reported or estimated), and the requesting user.
- **FR-007**: A job's capability, provider, model and version, inputs and seed MUST be written once
  at creation and MUST NOT change afterwards. When the operator gives no seed, a seed MUST be chosen
  and recorded so the request can be repeated.
- **FR-008**: Jobs MUST run in the background; the requesting screen MUST show progress without a
  manual reload.
- **FR-009**: As soon as a job succeeds, every output MUST be copied into Batchivo storage, owned by
  the job, and each output MUST record its kind (image or mesh), size, content type and image
  dimensions when known, and that it is AI-generated.
- **FR-010**: Completion MUST work by polling the provider (no public address needed); when a
  signed provider notification arrives with a valid signature, it MUST complete the job sooner.
  Notifications with an invalid or missing signature, or too old, MUST be rejected.
- **FR-011**: A job MUST complete exactly once even if polling and a notification both report it.
- **FR-012**: A queued or running job MUST be cancellable by the operator.
- **FR-013**: A job exceeding its capability's time limit MUST be canceled at the provider and
  marked failed with a timeout reason; transient provider errors MUST be retried a bounded number
  of times before the job fails.
- **FR-014**: Jobs MUST be listable by target and by status, newest first, paginated.
- **FR-015**: Starting, reading, listing, canceling jobs and adopting outputs MUST be available to
  non-HTTP callers through the same business rules as the screens (for feature 010's MCP tools).

**Adoption**

- **FR-016**: An output MUST be added to an idea, a product or a model only when the operator
  explicitly adopts it; nothing replaces or modifies an existing image or file on its own.
- **FR-017**: Adopting into an idea MUST create a timeline entry of kind generation in the idea's
  current iteration, linked to the job. A mesh entry MUST be viewable in the 3D viewer and
  downloadable.
- **FR-017a**: Converting an idea into a model (directly or through a product) MUST add each of the
  idea's adopted, non-archived 3D drafts to the new model as a file version labelled "AI draft",
  never active or primary; the conversion MUST still succeed when the idea has none.
- **FR-018**: Adopting an image into a product MUST add a new product image with origin AI; the
  source image MUST stay unchanged.
- **FR-019**: Adopting a mesh into a model MUST add a new model file version labelled as an AI draft,
  in a format the existing 3D viewer and measurement can read, and MUST NOT change which version is
  active or primary. Its measured size is recorded on the file for information only: an AI draft
  has no real-world scale, so it MUST NOT fill or change the model's dimensions.
- **FR-020**: Each output MUST record what it was adopted as (product image, idea entry or model
  file), and adopting the same output into the same target twice MUST be refused.

**Credentials, cost and safety**

- **FR-021**: The operator MUST be able to save, replace and remove a Replicate API token; it MUST
  be stored encrypted and shown only masked, and MUST NOT appear in any API response, frontend or
  log.
- **FR-022**: The operator MUST be able to test the connection with the saved token.
- **FR-023**: When the tenant has no token, a platform token from configuration MUST be used only
  if one is set AND a platform admin has authorised that tenant to use it (a per-tenant switch on
  the platform-admin tenant page, off by default; on a single-tenant VPS install the only tenant is
  authorised automatically). Tenant admins MUST NOT be able to grant this themselves. The settings
  page MUST say which token is in use (own, platform, or none).
- **FR-024**: The operator MUST be able to set a monthly budget (exact money amount, or none). A job
  whose estimated cost would take the month's spend over the budget MUST be refused before it is
  submitted.
- **FR-025**: The cost of every job (estimate before, final after) MUST be computed in one place
  only; money MUST be exact decimal and travel as decimal strings. Budget, job costs and usage are
  in US dollars (the provider's billing currency), labelled as such, with no currency conversion.
- **FR-026**: The settings page MUST show month-to-date spend and job count.
- **FR-027**: A tenant MUST NOT have more than a configured number of jobs queued or running at
  once; further requests MUST be refused with a clear reason.
- **FR-028**: Every product image MUST record its origin: photo, render (of the real geometry) or
  AI. Existing images MUST be treated as photos. The operator MUST be able to set an image's origin
  to photo or render.
- **FR-029**: AI-generated or AI-edited product images MUST display an "AI" badge in the image
  editor.
- **FR-030**: Adopting as a product image an output that is neither a photo of the product nor a
  render of its real geometry (a concept image or an image-to-3D output) MUST show a warning that
  listings must show the real item, and require confirmation.
- **FR-031**: All new data MUST be tenant-scoped: one tenant MUST never see, cancel or adopt
  another tenant's jobs or outputs, including through the provider notification path.
- **FR-032**: Input images MUST belong to the requesting tenant (its idea entries, product images,
  model images or prior job outputs); arbitrary external addresses MUST NOT be accepted as inputs.
- **FR-033**: Users with the owner, admin or member role MUST be able to start, cancel and adopt
  jobs; viewers MUST be able to list and read jobs and outputs but MUST be refused (forbidden) when
  starting, canceling or adopting, and the screens MUST hide those actions for them. Only owners and
  admins MUST be able to read or change Replicate settings (token, budget, overrides).

### Key Entities

- **Capability**: a kind of generation the system offers (concept image, image edit, product photo
  enhancement, background removal, upscale, lifestyle scene, image to 3D), with its input rules,
  output kind, time limit, and the provider model and pinned version it uses by default.
- **Generation job**: one request for a capability, by a user, for an optional target (idea,
  product, model). Holds immutable inputs (prompt, parameters, seed, input images) and model
  reference, a lifecycle status, the provider's job reference, an error, timings and cost with
  provenance.
- **Generated output**: one stored result of a job (image or mesh), always AI-generated, with its
  storage location, size, type and dimensions, and what it was adopted as.
- **Replicate settings (per tenant)**: encrypted token, monthly budget, per-capability model
  overrides.
- **Product image origin**: photo, render or AI, on every product image.
- **Idea timeline entry of kind generation** (exists since 007): gains the link to its job.
- **Model file version labelled AI draft**: a model file version created from an adopted mesh.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From an idea's page, an operator can go from "Generate concept" to an adopted concept
  image on the timeline in under 1 minute of their own time (excluding provider processing).
- **SC-002**: 100% of jobs that would exceed the monthly budget or the concurrency limit are refused
  before any cost is incurred.
- **SC-003**: 100% of succeeded jobs have all their outputs viewable in Batchivo more than one hour
  after completion (after the provider has deleted its copy).
- **SC-004**: For every job, an operator can read the exact capability, model version, prompt,
  parameters and seed that produced each output.
- **SC-005**: 100% of AI product images show the AI badge, and no concept image or 3D draft becomes
  a product image without the operator confirming the warning.
- **SC-006**: The provider token is never visible in any screen, API response or log line.
- **SC-007**: Jobs complete on an install with no public address (polling only), and complete
  faster when provider notifications reach the instance.

## Assumptions

- Estimated cost before submission comes from a per-capability price kept with the capability's
  model configuration (per output or per second of processing); the final cost is the provider's
  reported figure when available, else the estimate, with provenance recorded.
- The month for budget and usage is the calendar month in UTC.
- Default limits (overridable by configuration): 3 concurrent jobs per tenant, 4 images per concept
  request, 10-minute time limit for image capabilities and 30 minutes for image to 3D.
- Output images reuse the existing image storage rules (10 MB, thumbnails); meshes reuse the model
  file rules (size limit, measurement queue).
- The ideas module is enabled for AI actions on ideas; products and models pages show AI actions
  for every tenant with the 3D-print module. Backend routes are not module-gated, as today.
- Text capabilities (alt text, SEO copy), shop/storefront display of the AI badge, and marketplace
  disclosure checks before export are out of scope for 008.
- Feature 010 (MCP server) will expose capabilities, jobs and adoption as tools by calling the same
  service; personal API tokens and the "genai" scope belong to 010, not 008.
- Feature 009 (Preflight) may later call concept image for a design intent; nothing in 008 depends
  on 009.
