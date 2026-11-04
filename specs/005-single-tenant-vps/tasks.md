# Tasks: Single-Tenant VPS Edition

**Input**: Design documents from `specs/005-single-tenant-vps/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, contracts/cli.md, quickstart.md

**Tests**: required on every task that adds or changes code (Constitution II). Test tasks come
before the implementation they cover.

**Format**: `- [ ] T### [P?] [US#?] Description with file path`

---

## Phase 1: Setup

- [ ] T001 Create the bundle directory skeleton `deploy/vps/` with a `README.md` stub, and the package `backend/app/ops/__init__.py`
- [ ] T002 [P] Add test packages `backend/tests/guards/__init__.py` and `backend/tests/ops/__init__.py`, and register them in the existing pytest collection (no config change needed if `testpaths` already covers `tests/`; verify in `backend/pyproject.toml`)

---

## Phase 2: Foundational (blocks every story)

- [ ] T003 Write tests for the new settings in `backend/tests/unit/test_config_deployment_mode.py`: `deployment_mode` defaults to `"single"`, accepts only `single|multi`; `validate_for_mode()` returns every missing required name for single mode (`SECRET_KEY`, `DATABASE_URL`, `PUBLIC_BASE_URL`, `RESEND_API_KEY`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BATCHIVO_VERSION`) at once, raises only for `staging`/`production`, and only warns for `development`/`test` (research R5, FR-027)
- [ ] T004 Add `deployment_mode: Literal["single","multi"] = "single"`, `public_base_url`, `batchivo_version`, `backup_s3_endpoint`, `backup_s3_bucket`, `backup_s3_region`, `backup_s3_access_key_id`, `backup_s3_secret_access_key`, `backup_retention_days = 30`, `backup_schedule_hour = 3`, `instance_status_dir`, and `validate_for_mode()` to `backend/app/config.py` (FR-001, FR-027)
- [ ] T005 Set `DEPLOYMENT_MODE=multi` as the test-suite default and add `single_mode` / `multi_mode` override fixtures (clearing the settings `lru_cache`) in `backend/tests/conftest.py`
- [ ] T006 Write tests for `require_multi_mode` in `backend/tests/unit/test_mode_dependency.py`: 404 in single, pass-through in multi; `get_platform_admin` refuses (404) in single even for `is_platform_admin = true` (R2)
- [ ] T007 Implement `require_multi_mode` and the single-mode refusal inside `get_platform_admin` in `backend/app/auth/dependencies.py`

**Checkpoint**: the mode can be read and enforced; stories can start.

---

## Phase 3: User Story 1 — The shop's own identity everywhere a buyer looks (P1) 🎯 MVP

**Goal**: every buyer- and partner-facing identity value comes from the shop's settings (FR-010–FR-016).
**Independent test**: a tenant "Acme Prints" / `https://acme.example` walks product links, checkout, confirmation, emails, exports, Shopify sync and sitemap with no "mystmere" anywhere (quickstart §5, SC-001).

### Tests

- [ ] T008 [P] [US1] Write `backend/tests/unit/test_shop_identity.py`: `normalise_website_url` (adds `https`, lower-cases host, strips trailing slash, rejects path/query — "Normalised: scheme added (`https`), host lower-cased, no trailing slash, no path/query"); `resolve_shop_identity` precedence tenant setting → non-placeholder instance setting → `ShopIdentityIncomplete(fields)` listing every missing required field; placeholder defaults (`"Your Shop"`, `http://localhost:5173`, `noreply@example.com`) count as missing; `product_url` (seo_slug → `/products/{slug}`, else `/product/{id}`), `order_confirmation_url`, `site_url`; `reference_prefix` is the shop's `order_prefix`, else its slug
- [ ] T009 [P] [US1] Write `backend/tests/unit/test_shop_settings_identity_schema.py` for the new `ShopSettings` keys and their constraints: `email_from_address` "domain must equal the shop's own domain (website host or a parent of it, or the verified custom domain)"; `email_from_name` "≤ 100 chars"; `social_handle` "≤ 50 chars"; `sitemap_paths` "Each starts with `/`; ≤ 500 entries"
- [ ] T010 [P] [US1] Write `backend/tests/api/test_settings_shop_identity.py`: `GET/PUT /api/v1/settings/shop` round-trips the new fields (200), 401 without token, 403 for a non-owner write, 422 for an un-normalisable URL and for a sender address off the shop's domain
- [ ] T011 [P] [US1] Write `backend/tests/unit/test_commerce_order_ownership_ids.py`: the uuid5 event id for fixed inputs equals the value computed with the literal `mystmere:{tenant}:woocommerce:{id}:fulfilment:{state}:v1` (FR-013, SC-007)
- [ ] T012 [P] [US1] Write `backend/tests/api/test_identity_outputs.py` covering every row of data-model §3 for an "Acme Prints" tenant: hosted checkout redirect URL (`payments.py`), product sync `external_url` (`products.py`), storefront `shop_url` on all four listing endpoints (`shop.py`), sitemap base URL and `sitemap_paths`, handover 409/503 message, CSV export `Vendor`, Shopify payload `vendor`, Square `reference_id` prefix / `note` / quick-pay `name`; each contains Acme values and no "mystmere"
- [ ] T013 [P] [US1] Write `backend/tests/unit/test_email_service_identity.py`: every template renders `display_name`, `website_url`, `social_handle` and the sender from the passed `ShopIdentity`; an identity missing a required field raises before sending
- [ ] T014 [P] [US1] Write `backend/tests/unit/test_email_domain_status.py` (respx on Resend `GET /domains`): verified → sends; unverified or 401 key → no send from any other domain, error logged and reported, cached for 10 minutes; the order write path still succeeds (FR-012a, edge case)
- [ ] T015 [P] [US1] Write `backend/tests/api/test_shop_identity_incomplete.py`: `PUT /settings/shop` enabling the shop without `website_url` or `email_from_address` → 422 listing the missing fields; storefront and checkout routes for a tenant with incomplete identity → 503 "Shop identity incomplete: <fields>" (never 500, never another shop's value); single-mode start-up logs an error naming the tenant and its missing fields; the onboarding wizard's shop step requires website URL and sender address (FR-012)
- [ ] T016 [P] [US1] Write the derived guard `backend/tests/guards/test_no_hardcoded_shop_identity.py`: walk every file under `backend/app/`, `frontend/src/` and `infrastructure/k8s/`, fail on any case-insensitive `mystmere`; the only allowance is the constant `LEGACY_COMMERCE_ID_NAMESPACE`, matched by name, with its reason in the test (FR-016, R13)
- [ ] T017 [P] [US1] Write `frontend/src/components/products/ProductForm.test.tsx` case: the visibility section names the tenant's shop name, not a hard-coded shop
- [ ] T018 [P] [US1] Write `frontend/src/components/settings/ShopSettings.test.tsx` cases: identity fields render, validate (URL, sender domain) and submit to `PUT /settings/shop`

### Implementation

- [ ] T019 [US1] Extend `ShopSettings` with `website_url`, `email_from_address`, `email_from_name`, `orders_email`, `social_handle`, `sitemap_paths` and their validators (data-model §2) in `backend/app/schemas/tenant_settings.py`; rewrite the Mystmere description examples to `example-shop`
- [ ] T020 [US1] Create `backend/app/services/shop_identity.py`: `ShopIdentity`, `ShopIdentityIncomplete`, `normalise_website_url`, `resolve_shop_identity`, `product_url`, `order_confirmation_url`, `site_url` (research R6)
- [ ] T021 [US1] Expose the new fields on `GET/PUT /settings/shop` in `backend/app/api/v1/settings.py` and its response schema, owner-only for writes
- [ ] T022 [US1] Enforce required identity when the shop is enabled in `backend/app/api/v1/settings.py` and in the shop step of `backend/app/services/onboarding_wizard.py`; map `ShopIdentityIncomplete` to 503 with the field list via an exception handler in `backend/app/main.py`; log incomplete identities at single-mode start-up in `lifespan` (FR-012)
- [ ] T023 [US1] Replace the hard-coded confirmation URL in `backend/app/api/v1/payments.py:295` with `order_confirmation_url(resolve_shop_identity(shop_tenant), order_number)`
- [ ] T024 [US1] Replace `external_url` in `backend/app/api/v1/products.py:2985` with `product_url(...)`
- [ ] T025 [US1] Replace the four `shop_url` builders in `backend/app/api/v1/shop.py` (lines ~471, ~636, ~791, ~1017) with `product_url(...)`
- [ ] T026 [US1] Rebuild the sitemap in `backend/app/api/v1/shop.py:2319` from `identity.website_url` and `tenant.settings.shop.sitemap_paths` (default `/` and `/shop` plus product URLs) (R8)
- [ ] T027 [US1] Write the Alembic data migration `seed_shop_sitemap_paths` in `backend/alembic/versions/`: copy today's static page list and blog slugs into `sitemap_paths` for each tenant with `shop.enabled = true` and no key; copy env `SHOP_WEBSITE_URL` (normalised) into `website_url` when the tenant has none; idempotent; downgrade removes only keys it added; with a test in `backend/tests/migrations/test_seed_shop_sitemap_paths.py`
- [ ] T028 [US1] Build the handover message from `identity.website_url` in `backend/app/services/commerce_handover.py:53`
- [ ] T029 [P] [US1] Use `identity.display_name` for `Vendor` in `backend/app/services/export_service.py:166,546`
- [ ] T030 [P] [US1] Use `identity.display_name` for `vendor` in `backend/app/services/shopify_sync.py:288`
- [ ] T031 [US1] Use `identity.reference_prefix` for `reference_id` and `identity.display_name` for `note` and quick-pay `name` in `backend/app/services/square_payment.py:160-161,287`, passing the identity from its callers
- [ ] T032 [US1] Introduce `LEGACY_COMMERCE_ID_NAMESPACE = "mystmere"` with a frozen-identifier comment and use it in `backend/app/services/commerce_order_ownership.py:68` (output unchanged)
- [ ] T033 [US1] Refactor `backend/app/services/email_service.py` to take a `ShopIdentity` (sender, display name, website, social handle) instead of `settings.shop_*`; add `email_domain_status()` with a 10-minute cache and the no-fallback send refusal; update every caller (`customer_auth.py`, order/shipping/review email call sites) to pass `resolve_shop_identity(tenant)`
- [ ] T034 [US1] Rewrite the docstring/description examples in `backend/app/api/v1/shop_resolver.py`, `backend/app/auth/dependencies.py` and `backend/app/config.py:104` to `example-shop`
- [ ] T035 [P] [US1] Read the tenant's shop name in `frontend/src/components/products/ProductForm.tsx:535`
- [ ] T036 [P] [US1] Add the identity fields (website URL, sender name/address, orders email, social handle, sitemap paths) to the shop settings screen in `frontend/src/components/settings/` and its types in `frontend/src/types/` and API client in `frontend/src/lib/api/settings.ts`
- [ ] T037 [US1] Remove `SHOP_NAME`, `SHOP_WEBSITE_URL`, `SHOP_SOCIAL_HANDLE` (Mystmere values) from `infrastructure/k8s/backend/deployment.yaml` and rename the pod annotation `mystmere/native-release` to `batchivo/native-release` (same value; only a rollout trigger) (R9)

**Checkpoint**: US1 passes T008–T018; quickstart §5 holds.

---

## Phase 4: User Story 2 — A single-shop instance shows only what one shop needs (P1)

**Goal**: multi-shop capabilities hidden and refused in single mode, unchanged in multi; support through an owner-controlled, audited membership (FR-001–FR-009a).
**Independent test**: quickstart §2 in both modes; support account deactivation (story 2 scenario 6).

### Tests

- [ ] T038 [P] [US2] Write the derived guard `backend/tests/guards/test_mode_gated_routes.py`: enumerate `app.routes`; every route whose dependant tree contains `get_platform_admin`, plus `/shop-resolver/tenant/{slug}/config`, `/shop-resolver/tenant/{slug}/exists`, `/onboarding/register`, `/onboarding/verify-email`, `/onboarding/resend-verification`, answers 404 in single mode and is not 404 in multi mode; `/auth/register` is 403 in both; team members, tenant modules, custom-domain and sales-channel routes are **not** gated in single mode (FR-009)
- [ ] T039 [P] [US2] Write `backend/tests/api/test_instance.py`: `GET /api/v1/instance` returns `deployment_mode` and `version` in both modes, without auth
- [ ] T040 [P] [US2] Write `backend/tests/api/test_single_shop_resolution.py`: in single mode storefront routes and `/shop-resolver/resolve` resolve to the one tenant for any `X-Shop-Hostname`, with RLS context set; 503 "Instance not initialised" with zero tenants; 503 "Shop unavailable" when the only tenant is deactivated, with the reason in `instance-status` and no other tenant substituted; multi mode unchanged
- [ ] T041 [P] [US2] Write `backend/tests/unit/test_startup_single_mode.py`: start-up refuses with more than one active tenant and names their slugs (FR-005); starts with zero or one; `COMMERCE_TENANT_ID` defaults to the single tenant when unset
- [ ] T042 [P] [US2] Write `backend/tests/models/test_user_tenant_flags.py`: `is_active` "boolean, not null, default `true`", `is_support` "boolean, not null, default `false`"; migration upgrades existing rows and downgrades cleanly
- [ ] T043 [P] [US2] Write `backend/tests/api/test_member_activation.py`: deactivate/reactivate 200 for an owner, 401 without token, 403 for non-owner, 404 for a member of another tenant, 409 for an OWNER target and for the last active OWNER, 422 for a malformed id; a deactivated membership's token gets 401 on any authenticated route; `invite` with `is_support` is owner-only; list returns both flags; audit entries `member.deactivated` / `member.reactivated` written
- [ ] T044 [P] [US2] Write `backend/tests/unit/test_support_audit_middleware.py`: every POST/PUT/PATCH/DELETE under a support membership writes an `AuditService` entry (`support.request`, method, path, status, entity id when present); GETs and non-support members write none
- [ ] T045 [P] [US2] Write `frontend/src/hooks/useInstance.test.ts` and `frontend/src/components/guards/PlatformAdminGuard.test.tsx`: single mode redirects away from `/platform*` and hides the platform navigation entry and any registration link; multi mode unchanged
- [ ] T046 [P] [US2] Write `frontend/src/components/settings/TeamSettings.test.tsx` cases: support badge, active state, owner-only deactivate/reactivate controls, link to the audit log filtered by that user

### Implementation

- [ ] T047 [US2] Add `is_active` and `is_support` to `UserTenant` in `backend/app/models/user.py` and the Alembic migration `add_membership_active_and_support` (server defaults, reversible) in `backend/alembic/versions/`
- [ ] T048 [US2] Refuse an inactive membership (401) in `get_current_tenant` in `backend/app/auth/dependencies.py`
- [ ] T049 [US2] Add `POST /{member_id}/deactivate` and `/reactivate` (owner only, OWNER/last-owner protection, audit entries), `is_support` on invite, and both flags on list responses in `backend/app/api/v1/tenant_members.py` and its schemas
- [ ] T050 [US2] Create `backend/app/middleware/support_audit.py` and register it in `backend/app/main.py`
- [ ] T051 [US2] Attach `require_multi_mode` to the platform router include in `backend/app/main.py`, to `/tenant/{slug}/config` and `/tenant/{slug}/exists` in `backend/app/api/v1/shop_resolver.py`, and to `register`, `verify-email`, `resend-verification` in `backend/app/api/v1/onboarding.py`
- [ ] T052 [US2] Make `get_shop_tenant` and `/shop-resolver/resolve` single-mode aware (cached single tenant id, invalidated after first-run; 503 with zero tenants; 503 "Shop unavailable" when the only tenant is inactive) in `backend/app/auth/dependencies.py` and `backend/app/api/v1/shop_resolver.py`
- [ ] T053 [US2] Default `COMMERCE_TENANT_ID` to the single tenant in single mode in `backend/app/commerce_bridge.py`
- [ ] T054 [US2] Add the single-mode start-up checks (tenant count, `validate_for_mode()`) to `lifespan` in `backend/app/main.py`
- [ ] T055 [US2] Create `GET /api/v1/instance` in `backend/app/api/v1/instance.py` and mount it in `backend/app/main.py`
- [ ] T056 [P] [US2] Create `frontend/src/hooks/useInstance.ts` and `frontend/src/lib/api/instance.ts`
- [ ] T057 [US2] Use the mode in `frontend/src/components/guards/PlatformAdminGuard.tsx`, hide the platform navigation entry in `frontend/src/components/layout/` and registration links in `frontend/src/pages/`
- [ ] T058 [US2] Add support badge, active state and owner-only deactivate/reactivate controls to `frontend/src/components/settings/TeamSettings.tsx` and `frontend/src/lib/api/tenantMembers.ts`
- [ ] T059 [US2] Set `DEPLOYMENT_MODE: "single"` in `infrastructure/k8s/backend/deployment.yaml`

**Checkpoint**: US2 passes T038–T046; quickstart §2 holds.

---

## Phase 5: User Story 3 — Install a new customer's instance on a VPS (P2)

**Goal**: one documented procedure from empty VPS to owner login over HTTPS (FR-017–FR-021, FR-026–FR-028).
**Independent test**: quickstart §3 on a throwaway VPS.

### Tests

- [ ] T060 [P] [US3] Write `backend/tests/ops/test_init.py`: on an empty database creates exactly one tenant, one OWNER, optional support member (`is_support = true`, role ADMIN), leaves the wizard at step 1, prints DNS records; a second run exits 4 and changes nothing (FR-020, FR-021)
- [ ] T061 [P] [US3] Write `backend/tests/ops/test_host_cli_install.py` with a stub `docker` on PATH: `install` exits 2 listing each missing variable, fixes `.env` to mode 600, exits 3 on health timeout, prints `OK install`; `init` passes its arguments through (contracts/cli.md)
- [ ] T062 [P] [US3] Write `backend/tests/ops/test_vps_bundle.py`: `deploy/vps/docker-compose.yml` parses; Batchivo images use `${BATCHIVO_VERSION}`, third-party images are pinned by digest; monitoring services only in profile `monitoring`; every variable referenced by compose or required by `validate_for_mode()` appears in `.env.example`; `.woodpecker/build.yml` publishes both images on `event: tag` with `${CI_COMMIT_TAG}` tags (FR-019)

### Implementation

- [ ] T063 [US3] Create `backend/app/ops/init.py` (`python -m app.ops.init`) per contracts/cli.md
- [ ] T064 [US3] Map `STOREFRONT_ORIGINS` into the CORS allow-list in `backend/app/config.py` and `backend/app/main.py`, with tests in `backend/tests/unit/test_storefront_origins.py` (configured origin allowed, any other origin refused, empty → no browser origin) (FR-004a)
- [ ] T065 [US3] Create `deploy/vps/docker-compose.yml` (caddy, frontend, backend, postgres, redis, backup; `monitoring` profile with tempo, loki, prometheus, grafana) and `deploy/vps/Caddyfile` (`/api/*`, `/health` → backend; rest → frontend; HTTPS from `PUBLIC_BASE_URL`)
- [ ] T066 [US3] Create `deploy/vps/.env.example` with every variable grouped as in data-model §4, required-in-single marked
- [ ] T067 [US3] Create the host CLI `deploy/vps/batchivo` (POSIX sh) with `install`, `init`, `status` per contracts/cli.md
- [ ] T068 [US3] Add `postgresql16-client` and a `BATCHIVO_VERSION` build arg/env to `backend/Dockerfile`; pass `BATCHIVO_VERSION` to the frontend runtime config in `frontend/docker-entrypoint.sh`
- [ ] T069 [US3] Publish versioned images on `event: tag` (`v*`) with `${CI_COMMIT_TAG}` tags and the `BATCHIVO_VERSION` build arg in `.woodpecker/build.yml` (R12)
- [ ] T070 [US3] Write the provider install guide `docs-site/docs/self-hosting/vps-install.md` (prerequisites, Harbor robot pull account, DNS for HTTPS and for the customer's email domain, install, init) and link it from `docs-site/docs/self-hosting/overview.md`

**Checkpoint**: US3 passes T060–T062; quickstart §3 holds.

---

## Phase 6: User Story 4 — Update and back up an instance safely (P2)

**Goal**: manual per-instance update with backup first and rollback; scheduled backups to the customer's S3 (FR-022–FR-025).
**Independent test**: quickstart §4.

### Tests

- [ ] T071 [P] [US4] Write `backend/tests/ops/test_backup.py` against moto S3: `check` probe; `run` uploads key `batchivo/{yyyy}/{mm}/{yyyymmddTHHMMSSZ}-{version}.sql.gz` with metadata `batchivo-version`, `alembic-revision`, `created-at` and writes `last_backup.json`; `prune` deletes objects older than `BACKUP_RETENTION_DAYS` and never the newest; `restore` round-trips into an emptied database; `schedule` computes the next run at `BACKUP_SCHEDULE_HOUR` UTC; credential failure exits 5 and is reported
- [ ] T072 [P] [US4] Write `backend/tests/ops/test_host_cli_update.py` with a stub `docker`: success path order (check → backup → pin → pull → migrate → up → health); backup failure exits 5 with nothing changed (FR-024); migration failure exits 6, restores the previous `BATCHIVO_VERSION`, prints the backup key (FR-023); `latest` or no version exits 2
- [ ] T073 [P] [US4] Write `backend/tests/api/test_instance_status.py`: `GET /api/v1/settings/instance-status` 200 for owner with version, mode, email domain, last backup, missing identity fields; 401 without token; 403 for non-owner
- [ ] T074 [P] [US4] Write `frontend/src/components/dashboard/InstanceStatusBanner.test.tsx`: banner for unverified sender domain, failed or stale last backup, missing identity fields; hidden when all are fine

### Implementation

- [ ] T075 [US4] Create `backend/app/ops/backup.py` (`check`, `run`, `prune`, `restore`, `schedule`) per contracts/cli.md and data-model §5
- [ ] T076 [US4] Add `update`, `backup`, `restore` to `deploy/vps/batchivo` per contracts/cli.md, and the `backup` service running `python -m app.ops.backup schedule` in `deploy/vps/docker-compose.yml`
- [ ] T077 [US4] Create `GET /api/v1/settings/instance-status` in `backend/app/api/v1/settings.py`
- [ ] T078 [US4] Create `frontend/src/components/dashboard/InstanceStatusBanner.tsx` and show it on the dashboard and Settings → Shop
- [ ] T079 [US4] Write `docs-site/docs/self-hosting/vps-update-backup.md` (update, failed-update rollback, restore onto a new server, retention) and update `docs-site/docs/self-hosting/backup-restore.md` to point to it

**Checkpoint**: US4 passes T071–T074; quickstart §4 holds.

---

## Phase 7: Polish & Cross-Cutting

- [ ] T080 [P] Write `landing/tests/positioning.test.mjs` (`node --test`): `landing/app/page.tsx` and `landing/app/layout.tsx` contain no "open source", "self-host", "free forever" (case-insensitive) and contain a contact link (FR-029, SC-008)
- [ ] T081 Rewrite the landing copy in `landing/app/page.tsx` and metadata in `landing/app/layout.tsx` as a managed service with a contact link; leave `LICENSE` unchanged (FR-029, FR-030)
- [ ] T082 Add the landing test step to `.woodpecker/test-fast.yml`
- [ ] T083 [P] Update `CLAUDE.md` Quick Reference with the VPS commands (`deploy/vps/batchivo install|init|update|backup|restore|status`)
- [ ] T084 Before release, have the owner fill Settings → Shop for HandyLabs (name, website URL, sender address, social handle) on production and record the check of `/api/v1/instance`, the identity banner and a WooCommerce re-sync in `specs/005-single-tenant-vps/quickstart.md` §6 (FR-015, SC-002, SC-007)
- [ ] T085 Run the full gates (`poetry run pytest`, `ruff check`, `ruff format --check`, `npm test`, `npm run lint`, `npm run typecheck`, `node --test` in `landing/`) and fix any failure
- [ ] T086 Run quickstart §1–§2 locally and record the results in `specs/005-single-tenant-vps/quickstart.md` (VPS sections §3–§6 are run by the provider on real servers)

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → stories.
- **US1** and **US2** are independent of each other after Phase 2 (different files except
  `backend/app/main.py`, `backend/app/auth/dependencies.py` and
  `infrastructure/k8s/backend/deployment.yaml`, which run sequentially: T037 then T059; T022 before T054 in `main.py`; T048/T052
  after T007).
- T063 (first-run) calls the single-tenant cache invalidation added in T052.
- **US3** depends on US2 (single mode, start-up checks, first-run cache invalidation T052) and uses
  US1's identity for the init DNS output.
- **US4** depends on US3 (bundle and CLI exist).
- Polish after all stories; T084 before release, T085 last but one, T086 last.

## Parallel Examples

- US1 tests T008–T018 all [P]; then T029, T030, T035, T036 in parallel after T020.
- US2 tests T038–T046 all [P]; T056 in parallel with backend work.
- US3 tests T060–T062 [P]; US4 tests T071–T074 [P].

## Implementation Strategy

1. **MVP = Phase 1–3 (US1)**: the live HandyLabs shop stops showing Mystmere — valuable on its own
   and needed before any second customer.
2. Add **US2** and release to the cluster with `DEPLOYMENT_MODE=single` (quickstart §6).
3. Add **US3** + **US4**, then install the first customer VPS.
4. Polish (landing) can ship any time after US1.
