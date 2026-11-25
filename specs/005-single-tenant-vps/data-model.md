# Data Model: Single-Tenant VPS Edition

## 1. `user_tenants` (existing table) — two new columns

| Column | Type | Null | Default | Notes |
|--------|------|------|---------|-------|
| `is_active` | boolean | no | `true` | Membership can sign in to this tenant. Deactivation is per membership, not per user (FR-009a). |
| `is_support` | boolean | no | `false` | Marks the provider's support account; shown in the team list. |

- Tenant scope: unchanged (`tenant_id` FK, existing RLS policy on `user_tenants` covers the new
  columns).
- Constraints: an OWNER membership cannot be deactivated; the last active OWNER cannot be
  deactivated; only an OWNER may change `is_active` or set `is_support`.
- Migration: Alembic `add_membership_active_and_support`, server defaults so existing rows become
  `is_active = true`, `is_support = false`. Reversible.

## 2. `tenants.settings.shop` (existing JSONB, schema `ShopSettings`) — new keys

| Key | Type | Required when shop enabled | Validation |
|-----|------|----------------------------|------------|
| `website_url` | string | yes | Normalised: scheme added (`https`), host lower-cased, no trailing slash, no path/query (FR-014). |
| `email_from_address` | string | yes | Email; domain must equal the shop's own domain (website host or a parent of it, or the verified custom domain). |
| `email_from_name` | string | no (defaults to `shop_name`) | ≤ 100 chars. |
| `orders_email` | string | no (defaults to `email_from_address`) | Email. |
| `social_handle` | string | no | ≤ 50 chars, e.g. `@handylabs`. |
| `sitemap_paths` | list[string] | no | Each starts with `/`; ≤ 500 entries. |

Existing keys reused: `shop_name` (display name; falls back to `tenant.name`), `order_prefix`
(Square reference prefix), `custom_domain`, `custom_domain_verified`, `contact_email`.

- Not derived figures; plain configuration. No money involved.
- Data migration `seed_shop_sitemap_paths`: for each tenant with `shop.enabled = true` and no
  `sitemap_paths`, write the static page list and blog slugs currently hard-coded in
  `shop.py` (R8). If env `SHOP_WEBSITE_URL` is set at migration time and the tenant has no
  `website_url`, copy it (normalised). Idempotent; downgrade removes only keys it added.

## 3. Identity output inventory (every site that must call `ShopIdentity`)

| # | Location | Today | Becomes |
|---|----------|-------|---------|
| 1 | `api/v1/payments.py:295` | confirmation URL on mystmereforge.co.uk | `order_confirmation_url(identity, n)` |
| 2 | `api/v1/products.py:2985` | shop `external_url` | `product_url(identity, product)` |
| 3 | `api/v1/shop.py:471,636,791,1017` | `shop_url` of products | `product_url(identity, product)` |
| 4 | `api/v1/shop.py:2319` + page/blog lists | sitemap base and paths | `website_url` + `sitemap_paths` |
| 5 | `services/commerce_handover.py:53` | "reload www.mystmereforge.co.uk" | message built from `website_url` |
| 6 | `services/export_service.py:166,546` | `Vendor: Mystmereforge` | `display_name` |
| 7 | `services/shopify_sync.py:288` | `vendor: Mystmere Forge` | `display_name` |
| 8 | `services/square_payment.py:160-161,287` | reference prefix, note, quick-pay name | `reference_prefix`, `display_name` |
| 9 | `services/email_service.py` (all templates) | `settings.shop_*` | `ShopIdentity` passed in |
| 10 | `frontend/src/components/products/ProductForm.tsx:535` | "Mystmereforge Shop" | tenant shop name |
| 11 | `api/v1/shop_resolver.py`, `auth/dependencies.py`, `schemas/tenant_settings.py`, `config.py:104` | docstring/description examples | neutral `example-shop` |
| 12 | `services/commerce_order_ownership.py:68` | uuid5 name `mystmere:` | **unchanged output**, literal → `LEGACY_COMMERCE_ID_NAMESPACE` (R7) |
| 13 | `infrastructure/k8s/backend/deployment.yaml:45-50` | `SHOP_NAME`, `SHOP_WEBSITE_URL`, `SHOP_SOCIAL_HANDLE` = Mystmere | removed; tenant settings are the source. Pod annotation `mystmere/native-release` → `batchivo/native-release` |

`customer_auth.py` already uses `tenant.name`; it switches to `identity.display_name` for one
source.

## 4. Instance configuration (environment, not database)

Validated at start-up per mode (R5). Grouped in `deploy/vps/.env.example`:

- Instance: `DEPLOYMENT_MODE`, `BATCHIVO_VERSION`, `PUBLIC_BASE_URL`, `ENVIRONMENT`, `SECRET_KEY`.
- Database / cache: `POSTGRES_PASSWORD`, `DATABASE_URL`, `REDIS_URL`.
- Payments: `SQUARE_*` (customer's own account).
- Email: `RESEND_API_KEY` (customer's own account).
- Backups: `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_REGION`,
  `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BACKUP_RETENTION_DAYS` (default 30),
  `BACKUP_SCHEDULE_HOUR` (default 3, UTC).
- Storefront: `STOREFRONT_ORIGINS` (the customer's website origin(s) allowed by CORS; optional).
- Optional: `SENTRY_DSN`, `OTEL_*` (monitoring profile), `SHOPIFY_*`.

File permissions: `.env` owned by the instance user, mode `600` (Constitution, Additional
Constraints). `install` sets and `status` checks them.

## 5. Backup object (S3, not database)

- Key: `batchivo/{yyyy}/{mm}/{yyyymmddTHHMMSSZ}-{version}.sql.gz`.
- Metadata: `batchivo-version`, `alembic-revision`, `created-at`.
- `last_backup.json` on the shared status volume: `{ key, created_at, size_bytes, ok, error }`,
  read by `GET /api/v1/settings/instance-status`.
- Retention: objects older than `BACKUP_RETENTION_DAYS` deleted by `prune`, never the newest one.

## 6. State: instance lifecycle

```text
empty ──install──▶ running, 0 tenants ──init──▶ running, 1 tenant ──update──▶ running (vN+1)
                         │                            │                │ migration fails
                         └─ storefront 503            └─ backup ◀──────┴─▶ rolled back to vN
```
