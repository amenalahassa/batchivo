# Implementation Plan: Single-Tenant VPS Edition

**Branch**: `005-single-tenant-vps` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-single-tenant-vps/spec.md`

## Summary

Ship Batchivo as one instance per shop on a VPS without deleting the multi-tenant code. A
`DEPLOYMENT_MODE` instance setting (default `single`) gates the platform console, tenant
discovery and public tenant registration behind one dependency, and resolves the storefront to
the instance's only shop. Every buyer- and partner-facing identity value comes from one new
authority, `ShopIdentity`, fed by the tenant's shop settings — removing the hard-coded Mystmere
values while keeping already-stored external identifiers byte-identical. A `deploy/vps/` bundle
(Caddy HTTPS, compose, `.env.example`, a `batchivo` CLI) and Python operations in
`backend/app/ops/` provide first-run, manual per-instance update with backup first and rollback,
and scheduled backups to the customer's own S3 storage. Provider support uses a deactivatable,
audited support membership. Releases are versioned tags built by Woodpecker. The landing page is
rewritten as a managed service; the licence stays MIT. Details: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend, ops), TypeScript 5.9 (frontend, landing), POSIX sh (host CLI)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, Alembic, pydantic-settings, boto3 (S3 backups), httpx (Resend domain status); React 19, TanStack Query/Router, shadcn/ui; Next.js 16 (landing); Caddy 2, Docker Compose v2

**Storage**: PostgreSQL 16 (one database per instance); S3-compatible object storage owned by the customer (backups); a shared status volume for `last_backup.json`

**Testing**: pytest (+ moto for S3, respx for Resend, a stub `docker` on PATH for the host CLI), Vitest, `node --test` for the landing positioning check, manual VPS run per [quickstart.md](quickstart.md)

**Target Platform**: Linux VPS with Docker (customer instances); the existing k3s cluster (HandyLabs)

**Project Type**: web application (backend + frontend) plus deployment bundle

**Performance Goals**: install to first owner login < 30 min (SC-004); update downtime < 10 min (SC-005)

**Constraints**: no multi-tenant code removed (FR-008); stored identifiers unchanged (FR-013); one image for both modes (FR-007); every image built by CI and pinned (Constitution VII)

**Scale/Scope**: one shop per instance, tens of instances maintained by hand; 13 identity output sites (data-model §3); ~25 gated routes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How the design complies |
|-----------|--------|--------------------------|
| I. Multi-Tenant Isolation | ✅ | `tenant_id` and RLS stay on every table; new columns live on the RLS-covered `user_tenants`; storefront sessions keep `set_rls_context` with the single tenant; nothing switches to `get_db` for tenant data. |
| II. Tests Are Part of the Change | ✅ | Each new endpoint gets 200/401/403/404/422 tests; mode guard and identity guard derive their populations from the app; ops code tested with moto and a docker stub; landing check in CI. |
| III. One Authoritative Implementation | ✅ | `ShopIdentity` + its link builders are the single source for identity and shop URLs; `EmailService` stops reading `settings.shop_*` directly. |
| IV. Money Exact, Settings Honoured | ✅ | No money arithmetic touched. Placeholder defaults never shadow a tenant value; a missing value is an error, not a fallback. |
| V. Derived Figures Expire | ✅ | Nothing derived is stored; email-domain status cache is 10 min and only an operational signal. |
| VI. History Immutable | ✅ | Stored external identifiers keep their exact values (R7); no settled record restated. |
| VII. Deployment Through The Pipeline | ✅ | Releases are CI-built tags; VPSs pin a version, reject `latest`, update only via the documented command with backup first; the cluster keeps ArgoCD and its manifest change goes through it. |
| Additional Constraints | ✅ | Stack unchanged (Caddy/Compose are the bundle named in v1.1.0); Alembic migrations for the schema and data changes; secrets in K8s secrets on the cluster and in a `600` `.env` on VPSs. |

Post-design re-check: no violation; Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/005-single-tenant-vps/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api.md
│   └── cli.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py                       # deployment_mode, PUBLIC_BASE_URL, BACKUP_*, BATCHIVO_VERSION, validate_for_mode()
│   ├── main.py                         # lifespan checks; platform router gated; instance router; support audit middleware
│   ├── auth/dependencies.py            # require_multi_mode, single-shop get_shop_tenant, inactive membership → 401
│   ├── api/v1/
│   │   ├── instance.py                 # NEW GET /instance
│   │   ├── settings.py                 # shop identity fields, GET /settings/instance-status
│   │   ├── tenant_members.py           # deactivate/reactivate, is_support
│   │   ├── onboarding.py               # register/verify gated
│   │   ├── shop_resolver.py            # slug routes gated, /resolve single-aware
│   │   ├── payments.py, products.py, shop.py      # identity link builders, sitemap from settings
│   ├── services/
│   │   ├── shop_identity.py            # NEW authority
│   │   ├── email_service.py            # takes ShopIdentity; domain status
│   │   ├── square_payment.py, export_service.py, shopify_sync.py, commerce_handover.py
│   │   └── commerce_order_ownership.py # LEGACY_COMMERCE_ID_NAMESPACE
│   ├── middleware/support_audit.py     # NEW
│   ├── models/user.py                  # UserTenant.is_active, is_support
│   ├── schemas/tenant_settings.py      # ShopSettings new keys
│   └── ops/                            # NEW init.py, backup.py, __main__ helpers
├── alembic/versions/                   # membership columns; sitemap/website data migration
├── Dockerfile                          # postgresql16-client, BATCHIVO_VERSION build arg
└── tests/
    ├── guards/                         # identity guard, mode-gated routes
    ├── unit/                           # shop_identity, ownership ids, email status, config validation
    ├── api/                            # instance, instance-status, members, settings/shop, gated routes
    └── ops/                            # init, backup, host CLI with docker stub

frontend/src/
├── hooks/useInstance.ts                # NEW
├── components/guards/PlatformAdminGuard.tsx
├── components/layout/…                 # hide platform nav in single
├── components/settings/ShopSettings*.tsx, TeamSettings.tsx   # identity fields, support controls
├── components/dashboard/InstanceStatusBanner.tsx             # NEW email-domain / identity warnings
└── components/products/ProductForm.tsx

deploy/vps/                             # NEW docker-compose.yml, Caddyfile, .env.example, batchivo, README.md
landing/app/page.tsx, landing/tests/positioning.test.mjs
.woodpecker/build.yml                   # tag event → versioned images
infrastructure/k8s/backend/deployment.yaml   # DEPLOYMENT_MODE single, Mystmere SHOP_* removed
docs-site/docs/self-hosting/            # VPS install/update/backup pages
```

**Structure Decision**: existing web-application layout (`backend/`, `frontend/`), plus a new
top-level `deploy/vps/` for the per-customer bundle and `backend/app/ops/` for operations logic
that must be testable in Python.

## Complexity Tracking

No constitution violation to justify.
