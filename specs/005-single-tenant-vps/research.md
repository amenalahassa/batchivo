# Research: Single-Tenant VPS Edition

Decisions taken while planning `spec.md`. Each one is a constraint the code must keep.

## R1. Deployment mode is an instance setting, default `single`

- **Decision**: `deployment_mode: Literal["single", "multi"] = "single"` in `backend/app/config.py`
  (env `DEPLOYMENT_MODE`). The project cluster manifest sets it explicitly
  (`infrastructure/k8s/backend/deployment.yaml`). The test suite's base configuration sets
  `multi` so existing multi-tenant tests keep their meaning; single-mode tests opt in with an
  override fixture.
- **Rationale**: FR-001 (default single); one image for both modes (FR-007).
- **Alternatives**: build-time flag (rejected: FR-007); per-tenant flag (rejected: the mode is a
  property of the installation, not of a shop).

## R2. Gating multi-shop capabilities: one dependency, applied at router level

- **Decision**: `require_multi_mode` dependency in `backend/app/auth/dependencies.py`. It raises
  **404** in single mode, so the capability is indistinguishable from absent. It is attached to:
  - the whole `platform` router (`main.py` include, `dependencies=[...]`), which covers tenant
    list/detail, impersonation, deactivate/reactivate, platform modules and platform audit;
  - the slug-discovery routes of `shop_resolver.py` (`/tenant/{slug}/config`, `/tenant/{slug}/exists`);
    `/resolve` stays mounted and answers with the single shop (R4), because the storefront calls it;
  - `POST /api/v1/onboarding/register` and `POST /api/v1/onboarding/verify-email` and
    `resend-verification` — **these are an open public sign-up path today** (they create a tenant
    on verification), unlike `/auth/register`, which already returns 403 in every mode.
  `get_platform_admin` itself also refuses in single mode (defence in depth: a future platform
  route mounted elsewhere is covered too).
- **Rationale**: FR-002, FR-003, FR-008. A guard test derives the population from `app.routes`
  (every route whose dependant tree contains `get_platform_admin`, plus the discovery and
  registration routes) instead of a hand-written list.
- **Alternatives**: not mounting the routers in single mode (rejected: mode would then be fixed at
  import time and tests could not exercise both modes in one process).

## R3. The interface learns the mode from the instance

- **Decision**: public `GET /api/v1/instance` → `{ deployment_mode, version }`. Frontend hook
  `useInstance()`; `PlatformAdminGuard` redirects to `/` when the mode is `single`; the platform
  navigation entry is hidden; registration links are hidden.
- **Rationale**: FR-007 — same image, behaviour from the running instance. `version` comes from
  `BATCHIVO_VERSION` (set by the release image), used by the update report.

## R4. Shop resolution in single mode

- **Decision**: in single mode `get_shop_tenant` returns the instance's one active tenant whatever
  the `X-Shop-Hostname` (the header stays accepted for compatibility with the storefront repo).
  Its id is resolved once per process and cached; a tenant created by first-run invalidates the
  cache. No slug / subdomain / path lookup runs.
- **Rationale**: FR-004; there is no other shop to resolve to, so "another shop's subdomain" cannot
  resolve by construction.
- `COMMERCE_TENANT_ID` (`app/commerce_bridge.py`) defaults to that tenant in single mode when unset.

## R5. Start-up checks

- **Decision**: in `lifespan`, single mode:
  - more than one active tenant → refuse to start, error lists their slugs (FR-005);
  - zero tenants → start (first-run has not run); storefront routes answer 503 "instance not
    initialised";
  - required settings for the mode missing → refuse to start listing **every** missing name
    (FR-027). The check runs when `environment` is `staging` or `production`; `development` and
    `test` log a warning instead.
- Required in single mode: `SECRET_KEY`, `DATABASE_URL`, `PUBLIC_BASE_URL` (the instance's
  HTTPS origin), `RESEND_API_KEY`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`,
  `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BATCHIVO_VERSION`.

## R6. One authority for shop identity

- **Decision**: new `backend/app/services/shop_identity.py`:
  - `ShopIdentity` (frozen dataclass): `display_name`, `website_url` (normalised),
    `email_from_address`, `email_from_name`, `orders_email`, `social_handle`, `reference_prefix`.
  - `resolve_shop_identity(tenant) -> ShopIdentity`: reads `tenant.settings.shop`; for a field the
    tenant has not set, uses the instance setting **only if it is not the placeholder default**
    (`"Your Shop"`, `http://localhost:5173`, `noreply@example.com`, …). A required field still
    missing raises `ShopIdentityIncomplete(fields)` (FR-012). Never another shop's value.
  - link builders: `product_url(identity, product)` (seo_slug → `/products/{slug}`, else
    `/product/{id}`), `order_confirmation_url(identity, order_number)`, `site_url(identity, path)`.
  - `normalise_website_url(value)`: adds `https://` when no scheme, lower-cases the host, strips
    the trailing slash, rejects a path/query (FR-014).
- Every output site in the inventory (data-model.md §3) calls it; `EmailService` takes a
  `ShopIdentity` instead of reading `settings.shop_*` directly.
- **Rationale**: FR-010, FR-012, FR-014; Constitution III (one implementation) and IV (a configured
  value wins over a hard-coded default).

## R7. Identifiers already stored stay stable

- **Decision**:
  - `commerce_order_ownership.py` uuid5 name `mystmere:{tenant.id}:woocommerce:...` → the literal
    becomes the constant `LEGACY_COMMERCE_ID_NAMESPACE = "mystmere"` with a comment that it is a
    frozen identifier, not branding. Output is byte-identical (FR-013, SC-007).
  - Square `reference_id`: new payments use `{reference_prefix}-{key[:8]}` where `reference_prefix`
    is the shop's `order_prefix` (or slug). Stored references are never recomputed (they live on
    `payment_logs` / Square), so existing records are untouched. Square `note` and quick-pay
    `name` use `display_name`.
- The hard-coded-identity guard (R13) allow-lists exactly `LEGACY_COMMERCE_ID_NAMESPACE`, by name,
  with this reason.

## R8. Sitemap content is shop data

- **Decision**: `shop.py` sitemap: `base_url` from `ShopIdentity.website_url`; the static page
  list and the blog slugs (Mystmere storefront content such as `/dragons`) move to
  `tenant.settings.shop.sitemap_paths: list[str]`. An Alembic data migration copies the current
  lists into every tenant whose shop is enabled, so their sitemap output is unchanged except its
  base URL. A tenant without the key gets only `/` and `/shop` plus product URLs.

## R9. HandyLabs is configured by data

- **Decision**: the Settings → Shop screen gains the identity fields (website URL, email sender
  name/address, orders email, social handle). The live tenant is renamed and filled in there by
  its owner (quickstart §6). The cluster manifest drops `SHOP_NAME`, `SHOP_WEBSITE_URL`,
  `SHOP_SOCIAL_HANDLE` (Mystmere values) so the tenant settings are the only source.
- **Open data input**: HandyLabs's website URL, sender address and social handle are supplied by
  the owner at release time; they are data, not part of the code.

## R10. Support account

- **Decision**: membership-level flags on `user_tenants`: `is_active` (default true) and
  `is_support` (default false). Authentication refuses a token whose membership for the token's
  tenant is inactive (checked in `get_current_tenant`). New endpoints (OWNER only):
  `POST /api/v1/tenant/members/{id}/deactivate` and `/reactivate`. The team list shows both flags.
  Created by first-run (`--support-email`) or by an owner invite with `is_support: true`.
- **Audit**: a request middleware records every mutating request (POST/PUT/PATCH/DELETE) made
  under a support membership through `AuditService.log` (action `support.request`, method, path,
  status code, entity id when the path carries one). The team screen links to the audit log
  filtered by that user.
- **Rationale**: FR-009a; reuses memberships, roles and the audit log rather than a hidden admin.
- **Alternatives**: `User.is_active` (rejected: global across tenants, wrong in multi mode).

## R11. VPS bundle and operations

- **Decision**: new `deploy/vps/`:
  - `docker-compose.yml`: `caddy` (automatic HTTPS from `PUBLIC_BASE_URL`), `frontend`,
    `backend`, `postgres:16-alpine`, `redis:7-alpine`, `backup` (backend image running the backup
    scheduler). Profile `monitoring`: tempo, loki, prometheus, grafana (from the existing root
    compose). Third-party images pinned by digest; Batchivo images by `${BATCHIVO_VERSION}`.
  - `Caddyfile`: `/api/*` and `/health` → backend, everything else → frontend (the management
    console). No storefront is served: buyers use the customer's own site, Shopify or Etsy
    (clarification 2026-11-03).
  - `STOREFRONT_ORIGINS` (comma-separated) feeds the existing CORS allow-list, so the customer's
    own website can call the API from the browser; empty means server-to-server only (FR-004a).
  - `.env.example`: every variable, grouped, required-in-single marked (FR-026).
  - `batchivo` (POSIX sh) CLI: `install`, `init`, `update <version>`, `backup`, `restore <key>`,
    `status`. It only orchestrates `docker compose`; logic lives in Python.
- Python operations in `backend/app/ops/` (testable with pytest, moto for S3):
  - `init.py`: `alembic upgrade head`; refuses if any tenant or user exists (FR-021); creates the
    tenant (single), the owner (sends the password-set email, prints the link as fallback), the
    optional support member; onboarding wizard status left at step 1 (FR-020).
  - `backup.py`: `run` (pg_dump → gzip → S3 key `batchivo/{yyyy}/{mm}/{timestamp}.sql.gz`, writes
    `last_backup.json` to the shared status volume), `prune` (retention days), `restore <key>`,
    `schedule` (sleeps to `BACKUP_SCHEDULE_HOUR` daily, then run + prune), `check` (write-probe
    used before an update — FR-024).
  - The backend runtime image gains `postgresql16-client` (pg_dump / psql).
- `update <version>`: `backup check` → `backup run` (abort on failure) → record previous version →
  set `BATCHIVO_VERSION` → `compose pull` → `compose run --rm backend alembic upgrade head` → on
  failure restore previous `BATCHIVO_VERSION`, bring it back up, print the backup key and the
  restore command (FR-023) → `compose up -d` → wait for `/health` → report version and outcome.
  `latest` is rejected as a version argument (Constitution VII).
  - *Cross-reference (spec 006, research D10):* after `alembic upgrade head`, `update` also runs
    `compose run --rm backend python -m app.cli.seed_catalogues --all-tenants`, the same release
    step the cluster's init container runs. It is idempotent, so `init` may run it too.

## R12. Releases

- **Decision**: `.woodpecker/build.yml` also runs on `event: tag` matching `v*`, pushing
  `batchivo-backend:${CI_COMMIT_TAG}` and `batchivo-frontend:${CI_COMMIT_TAG}` (plus the SHA tag),
  with `BATCHIVO_VERSION` baked in as a build arg. Customer VPSs pull from
  `registry.techize.co.uk` with a read-only Harbor robot account per customer.

## R13. Hard-coded identity guard

- **Decision**: `backend/tests/guards/test_no_hardcoded_shop_identity.py` walks every file under
  `backend/app/` and `frontend/src/` (derived population, not a list) and fails on any
  case-insensitive `mystmere` occurrence. The only allowance is the named constant of R7, by name
  and with its reason; docstring examples are rewritten to `example-shop`. Runs in the existing CI test stage
  (FR-016).

## R14. Email from the customer's own domain

- **Decision**: `ShopIdentity.email_from_address` must be on the shop's own domain and verified
  in the customer's Resend account. `email_domain_status()` in `email_service.py` asks Resend
  (`GET /domains`) and caches the answer for 10 minutes. When not verified (or the key is
  revoked): no email is sent from any other domain, the failure is logged and reported to Sentry,
  and the owner sees a banner on the dashboard and Settings → Shop; orders are still recorded
  (FR-012a and its edge case). `init` prints the DNS records Resend requires.

## R15. Landing page

- **Decision**: `landing/app/page.tsx` copy rewritten as a managed service (install, host,
  update, back up your own instance) with a contact link; no mention of open source,
  self-installation or "free forever" (FR-029). `LICENSE` untouched (FR-030). A `node --test`
  check in `landing/tests/positioning.test.mjs` fails on the forbidden phrases, wired into CI.
