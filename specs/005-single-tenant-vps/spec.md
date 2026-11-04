# Feature Specification: Single-Tenant VPS Edition

**Feature Branch**: `005-single-tenant-vps`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "Single-tenant VPS edition: one Batchivo instance per shop, behind a deployment-mode flag, with the shop identity taken from the tenant's settings. The licence stays MIT." Full prompt: `specs/backlog.md` → "Single-tenant VPS edition: one installed instance per shop".

## Context

Batchivo is multi-tenant in its data model (every record belongs to a tenant, with
memberships, roles, a platform admin console and shop resolution by subdomain, path or
custom domain) but is sold and operated as **one business per installation**. The new
business model is to offer each 3D-print shop owner its own Batchivo instance on a VPS,
with its own database and its own payment and email credentials, that can grow with their
needs (team members, modules, custom domain, marketplace channels).

Two problems block that today:

1. The shop identity of one business (Mystmere Forge: name, website, product and order
   confirmation URLs, vendor name, payment references, email sender, social handle) is
   written into the product instead of coming from the shop's own settings. A second
   customer's buyers would be sent to Mystmere's website. The current production account
   is **HandyLabs**, not Mystmere.
2. There is no way to install, start, update and back up one instance on a plain VPS: the
   only deployment is the project owner's own cluster.

The multi-tenant capabilities are **kept, not deleted**: a deployment-mode setting
switches them off for a single-shop instance and back on for a hosted multi-shop service.

## Clarifications

### Session 2026-11-03

- Q: How are updates triggered on customer VPSs? → A: The provider runs the update command manually on each VPS (over SSH), customer by customer; no automatic or central fleet update.
- Q: What access does the provider have to a customer's instance for support? → A: A "support" member account of the shop, which the owner can deactivate, with its actions recorded in the audit log; no hidden platform admin.
- Q: Where do off-server backups go? → A: To the customer's own S3-compatible storage, with the customer's credentials.
- Q: What does the public landing page say now that the licence stays MIT? → A: It no longer mentions open source; it presents only the managed service (install and run your instance). The code stays MIT on GitHub.
- Q: Which address do a customer's order emails come from? → A: The customer's own domain, through the customer's own email-sending account, with DNS verification done at install.
- Q: Which storefront do buyers use on a customer VPS? → A: The customer's own site (Shopify, Etsy, or their own website) connected to the instance's API; the bundle serves the API and the management console only, no storefront.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The shop's own identity everywhere a buyer looks (Priority: P1)

As a shop owner running my own instance, every buyer-facing touchpoint — product links,
order confirmation page, emails, payment descriptions, exported catalogues, marketplace
listings — shows **my** shop's name, website and handle, configured in my settings, never
another shop's.

**Why this priority**: Without it, the product cannot be given to a second customer at
all: their buyers would land on another business's site and see another brand on their
payment. It is also needed now, because the live account is HandyLabs and still shows
Mystmere.

**Independent Test**: Configure a shop with a name and website different from any
existing business, then walk a product page, a checkout, an order confirmation, an
email, a catalogue export and a marketplace sync; no output names any other shop.

**Acceptance Scenarios**:

1. **Given** a shop configured with name "HandyLabs" and website `https://handylabs.example`, **When** a buyer views a product and completes a purchase, **Then** the product link, the payment description and the order confirmation link all use HandyLabs and `https://handylabs.example`.
2. **Given** that shop, **When** the operator exports the catalogue or syncs to a marketplace, **Then** the vendor field reads "HandyLabs".
3. **Given** that shop, **When** an order confirmation email is sent, **Then** the sender display name and reply address are the ones configured for that shop.
4. **Given** a shop with no website configured, **When** a buyer-facing link must be built, **Then** the operator is told during setup or onboarding that the website is required, and no link pointing at another shop is ever produced.
5. **Given** orders recorded before this change, **When** they are re-synced or re-processed, **Then** their existing external identifiers are unchanged and no duplicate order is created.
6. **Given** the operator edits a product, **When** they read the visibility section, **Then** it names their own shop, not a hard-coded one.

---

### User Story 2 - A single-shop instance shows only what one shop needs (Priority: P1)

As a shop owner on my own instance, I see and can reach only my shop: no sign-up page for
strangers, no list of other businesses, no platform administration, no "log in as another
shop".

**Why this priority**: An instance per customer must not expose hosting-operator tools
or an open sign-up that would create stray shops on the customer's server. It is the
switch that makes the existing multi-tenant code safe to ship to customers unchanged.

**Independent Test**: Start an instance in single-shop mode and try each multi-shop
capability through the interface and directly; each is absent from the interface and
refused when called directly. Restart in multi-shop mode; each works as before.

**Acceptance Scenarios**:

1. **Given** an instance in single-shop mode, **When** a visitor tries to register an account, **Then** registration is refused.
2. **Given** single-shop mode, **When** any user — including one flagged as a platform administrator — opens the platform administration, tenant listing, tenant deactivation or impersonation, **Then** the interface does not offer it and a direct request is refused.
3. **Given** single-shop mode and the customer's own storefront (their website, or a Shopify/Etsy shop) connected to the instance's API, **When** that storefront requests shop data or places an order, **Then** the request is served for the one shop without any subdomain, path or hostname identifying it.
4. **Given** single-shop mode, **When** someone requests the shop through another shop's subdomain or path, **Then** the request does not resolve to any other shop.
5. **Given** an instance in multi-shop mode, **When** the same capabilities are used, **Then** they behave exactly as before this feature.
6. **Given** single-shop mode with a support account, **When** the owner deactivates it, **Then** the support account cannot sign in, and every action it took before is listed in the audit log under its name.
7. **Given** single-shop mode, **When** the owner invites team members and assigns roles or enables modules, **Then** those work as before — growing the shop stays possible.
8. **Given** the same application release, **When** it is started once in each mode, **Then** the interface adapts to the mode without a different build.

---

### User Story 3 - Install a new customer's instance on a VPS (Priority: P2)

As the provider, I can take a fresh VPS and, with one documented procedure, have a
customer's instance running over HTTPS on their domain, with their owner account created
and the onboarding wizard waiting for them.

**Why this priority**: It is the delivery step of the business model. It depends on
Stories 1 and 2 to be safe, but can be tested on its own on a throwaway server.

**Independent Test**: On an empty VPS with a domain pointed at it, follow the install
procedure from the documentation only; the owner logs in over HTTPS and lands on
onboarding.

**Acceptance Scenarios**:

1. **Given** an empty VPS with a container runtime and a domain pointed at it, **When** the provider fills in the instance configuration and runs the install, **Then** the application, its database, its cache and an HTTPS front door start, and a valid certificate is obtained automatically.
2. **Given** a running fresh instance, **When** the first-run step is executed with the shop name and owner email, **Then** the database schema is created, exactly one shop and one owner account exist, and the owner's first login opens the existing onboarding wizard.
3. **Given** first-run has already been executed, **When** it is run again, **Then** it refuses to create a second shop or owner and changes nothing.
4. **Given** the instance configuration file, **When** a required value for single-shop mode is missing, **Then** start-up stops with a message naming the missing value.
5. **Given** the install, **When** the provider does not enable monitoring, **Then** the instance runs without the tracing, logging and dashboard stack, and error reporting still works if its key is provided.

---

### User Story 4 - Update and back up an instance safely (Priority: P2)

As the provider maintaining many customer instances, I can update one to a chosen release
and I know its data is backed up off the server on a schedule and can be restored.

**Why this priority**: With one instance per customer, updates and backups are repeated
on every server; a failed update or a lost disk must never cost a customer their data.

**Independent Test**: On a throwaway instance with data, run an update to a newer
release, then simulate a failing update, then restore from the off-server backup; the
data survives each step.

**Acceptance Scenarios**:

1. **Given** a running instance, **When** the provider runs the update to a pinned release, **Then** a backup is taken first, the release is fetched, the database is migrated, the application restarts and the result is reported.
2. **Given** an update whose database migration fails, **When** the update stops, **Then** the backup taken before it and the previous release remain available, and the documented restore returns the instance to its prior state.
3. **Given** a running instance, **When** the scheduled backup runs, **Then** a database backup is written to an off-server destination and backups older than the retention period are removed.
4. **Given** a backup, **When** the provider follows the documented restore on a new server, **Then** the instance comes back with its data.
5. **Given** releases published by the build pipeline, **When** an instance is updated, **Then** it uses a versioned release identifier, never a moving "latest".

---

### Edge Cases

- A single-shop instance whose database already contains more than one shop (an old multi-shop dump restored onto a VPS): start-up refuses single-shop mode and names the shops found, rather than picking one.
- A single-shop instance whose only shop is deactivated: the shop is unavailable to buyers and the owner sees why; no other shop is substituted.
- A user flagged as platform administrator on a single-shop instance: keeps their role in the shop but gets no platform capability.
- The owner deactivates the support account: the provider can no longer sign in to the application until the owner reactivates it; server-level maintenance (update, backup) is unaffected.
- A custom domain configured but not yet verified: the unverified domain is not used for buyer links until verified; links use the shop's website address.
- A browser storefront calls the API from an origin that is not configured: the call is refused by the browser's cross-origin rules and nothing is served to it.
- A shop website configured with a trailing slash, without scheme, or with uppercase: links are built consistently and never with a double slash.
- Historic external identifiers (marketplace order ownership keys, payment references) derived from the old shop prefix: kept as-is for existing records so re-syncs match; only new records may use the shop's own identity, and never in a way that changes an identifier already stored.
- The customer's storage credentials are missing, wrong or revoked: the scheduled backup reports the failure to the provider (and to error reporting when configured), and the update refuses to start (FR-024); the instance itself keeps running.
- The customer's sending domain is not verified, or its email account key is revoked: order emails are not sent from any other domain; the failure is shown to the owner and reported to the provider, and orders themselves are still recorded.
- An update run on an instance that has not been backed up in the retention window and whose backup destination is unreachable: the update stops before changing anything.
- Switching an existing instance from multi-shop to single-shop mode: allowed only when exactly one active shop exists.
- The cluster deployment used today (HandyLabs) switches to single-shop mode: its data, settings and integrations keep working; it is not required to move to a VPS.

## Requirements *(mandatory)*

### Functional Requirements

**Deployment mode**

- **FR-001**: The system MUST support a deployment mode setting with two values: single-shop and multi-shop. The default for a new installation MUST be single-shop.
- **FR-002**: In single-shop mode, the system MUST refuse public account registration.
- **FR-003**: In single-shop mode, the system MUST hide from the interface and refuse on direct request: platform administration, tenant listing and detail, tenant deactivation and reactivation, impersonation, platform module administration and the platform audit view.
- **FR-004**: In single-shop mode, every storefront request to the instance's API MUST resolve to the instance's one shop without requiring a subdomain, path or hostname; subdomain and path resolution of other shops MUST NOT resolve. The buyer-facing storefront is the customer's own site (their website, Shopify or Etsy) connected to the API; the instance does not serve a storefront.
- **FR-004a**: The instance MUST accept browser API calls from the customer's storefront origin(s) configured for the instance, and from no other origin.
- **FR-005**: In single-shop mode, the system MUST refuse to start when the database holds more than one active shop, and MUST name them.
- **FR-006**: In multi-shop mode, every capability listed in FR-002 to FR-004 MUST behave as it did before this feature.
- **FR-007**: The interface MUST learn the deployment mode from the running instance, so the same release serves both modes.
- **FR-008**: No multi-shop capability MUST be removed from the product; each MUST be gated by the deployment mode.
- **FR-009**: Team membership, roles, module enablement, custom domains and sales channels MUST remain available in single-shop mode.
- **FR-009a**: In single-shop mode, provider support MUST happen through a support member account of the shop: it is visible in the team list, the owner can deactivate and reactivate it, and every change it makes is recorded in the audit log under that account. A hidden or always-on administrator account MUST NOT exist.

**Shop identity**

- **FR-010**: Every buyer-facing and partner-facing identity value MUST come from the shop's settings or the instance configuration: shop display name, shop website base address, product page links, order confirmation link, vendor name in catalogue exports and marketplace sync, payment order name and description, email sender name and address, social handle, the maintenance/hand-over message shown to buyers, and the shop name shown in the product visibility section.
- **FR-011**: The product MUST NOT contain any hard-coded name, address or handle of a specific customer's shop in code paths that produce output; examples in documentation and descriptions MUST use a neutral placeholder.
- **FR-012**: A required identity value that is missing MUST be reported as a configuration error at start-up or during onboarding; the system MUST NOT fall back to another shop's identity.
- **FR-012a**: Order emails MUST be sent from an address on the shop's own domain through the customer's own email-sending account; the install procedure MUST include verifying that domain for sending, and the instance MUST report a sending domain that is not verified instead of sending from another domain.
- **FR-013**: External identifiers already stored for existing records (marketplace order ownership keys, payment reference identifiers) MUST NOT change as a result of this feature; re-processing an existing record MUST produce the same identifier as before.
- **FR-014**: Shop website addresses MUST be normalised when building links (scheme, trailing slash, case of the host) so the same configured value always yields the same link.
- **FR-015**: The current production shop MUST be configured as HandyLabs through its settings and data, not through code.
- **FR-016**: An automated check MUST fail the build when a hard-coded shop identity reappears in output-producing code.

**Install, first run, update, backup**

- **FR-017**: The product MUST provide an installation bundle for one VPS that starts the application, its database, its cache and an HTTPS front door that obtains and renews certificates automatically.
- **FR-018**: Monitoring components (tracing, log aggregation, metrics, dashboards) MUST be optional in the bundle; error reporting MUST work when its key is configured.
- **FR-019**: The build pipeline MUST publish versioned releases that a customer VPS can fetch; instances MUST reference a pinned version.
- **FR-020**: The product MUST provide a first-run step that applies the database schema, creates the single shop and its owner account, and leads the owner into the existing onboarding wizard on first login.
- **FR-021**: The first-run step MUST refuse to run when a shop or owner already exists, and change nothing.
- **FR-022**: The product MUST provide an update step, run manually by the provider on one instance at a time, that backs up the database, fetches the pinned release, migrates the database, restarts the application and reports the outcome.
- **FR-023**: When the update's migration fails, the update MUST stop and leave both the pre-update backup and the previous release available for restore.
- **FR-024**: The update MUST NOT start when no backup can be written.
- **FR-025**: The product MUST provide scheduled database backups to the customer's own S3-compatible storage (endpoint, bucket and credentials supplied by the customer in the instance configuration) with a configurable retention period, and a documented restore procedure that works from that storage onto a new server.
- **FR-026**: The product MUST provide a configuration example listing every setting an instance needs, marking which are required in single-shop mode.
- **FR-027**: Start-up MUST stop with a message naming each missing required setting for the selected mode.
- **FR-028**: Instance secrets (payment, email, database, signing keys) MUST be supplied through the instance configuration on the VPS and MUST NOT be committed to the repository.

**Public positioning**

- **FR-029**: The landing page MUST present Batchivo as a managed service (the provider installs, hosts, updates and backs up the shop's own instance) with a way to contact the provider, and MUST NOT mention open source, self-installation or "free forever".
- **FR-030**: The licence file and the source repository MUST stay under MIT; the landing change MUST NOT alter the licence or remove licence notices.

### Key Entities

- **Deployment mode**: an instance-level setting (single-shop / multi-shop) that gates multi-shop capabilities; read at start-up and exposed to the interface.
- **Shop (tenant) identity**: the existing shop record and its settings, extended where needed to hold display name, website base address, email sender name and address, and social handle; the single source for every buyer-facing identity value.
- **Instance configuration**: the per-VPS set of settings and secrets (mode, domain, database, payment and email credentials, the customer's backup storage endpoint, bucket and credentials, retention, optional monitoring and error-reporting keys).
- **Release**: a versioned, published build that an instance pins and updates to.
- **Backup**: a timestamped database export stored off-server, subject to retention, restorable onto a new server.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a shop configured under any name other than Mystmere Forge, 0 buyer-facing or partner-facing outputs (product links, confirmation links, emails, payment descriptions, exports, marketplace listings) name or link to Mystmere Forge.
- **SC-002**: The live HandyLabs shop shows "HandyLabs" and its own website in 100% of those outputs after release.
- **SC-003**: In single-shop mode, 100% of the multi-shop capabilities listed in FR-003 are absent from the interface and refused on direct request; in multi-shop mode, 100% behave as before.
- **SC-004**: A provider following only the documentation brings a new customer instance from an empty VPS to the owner's first login over HTTPS in under 30 minutes.
- **SC-005**: An update of an instance to a new release completes in under 10 minutes of downtime, and a deliberately failed update is restored to the prior state with no data loss.
- **SC-006**: A backup taken by the schedule can be restored onto a new server with 100% of shop records present.
- **SC-007**: Re-processing every existing order after release produces 0 changed external identifiers and 0 duplicate orders.
- **SC-008**: The landing page contains 0 mentions of open source, self-installation or "free forever", and offers a contact path to the managed service.

## Assumptions

- One customer = one VPS = one shop. Multi-shop hosting stays possible through the mode flag but is not the target of this release.
- The VPS runs a standard container runtime; the provider installs and maintains instances (customers do not self-install). Updates are started by hand per instance; automatic updates and a central fleet console are out of scope.
- The existing project-owner cluster keeps its pipeline-based deployment; HandyLabs switches to single-shop mode there and is not required to move to a VPS in this feature.
- Customer instances fetch releases built by the existing CI pipeline; they are never built by hand. Constitution v1.1.0 (2026-11-03) covers this path: Principle VII (CI-built pinned releases, provider-run install/update with backup first) and the secrets rule (instance configuration file on the VPS, owner-only).
- Backups live in storage the customer owns and pays for; restoring onto a new server needs the customer to keep (or re-share) those storage credentials.
- Each customer owns its email-sending account and the DNS of its domain; the provider performs the verification at install with the customer's access.
- Each instance has its own payment and email credentials; per-shop credentials inside one instance are not needed in single-shop mode.
- Row-level security can be enabled per instance; with one shop per database it is defence in depth, not the isolation between customers.
- The licence stays MIT (copyright Jonathan Gill). The business model sells installation, hosting and support of instances, not a licence; no licence change is part of this feature. Only the landing page's positioning changes (FR-029); README and documentation wording are left as they are.
- Knitting and other craft modules remain out of scope.
- No storefront is shipped in the VPS bundle; the existing `mystmereforge-shop` storefront repository is not part of this edition. Shopify and Etsy shops connect through the existing sales-channel integrations.
