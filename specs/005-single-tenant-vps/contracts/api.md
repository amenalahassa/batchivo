# API Contract: Single-Tenant VPS Edition

Prefix `/api/v1`. Auth tiers: **public**, **member** (any active membership), **owner**
(OWNER role). Error bodies are FastAPI's `{"detail": ...}`.

## New endpoints

### `GET /instance` — public

```json
200 { "deployment_mode": "single" | "multi", "version": "v1.4.0" }
```

No 401/404/422 case (no input, no auth). Version is `BATCHIVO_VERSION` or `"dev"`.

### `GET /settings/instance-status` — owner

```json
200 {
  "deployment_mode": "single",
  "version": "v1.4.0",
  "email_domain": { "domain": "handylabs.example", "verified": true, "checked_at": "..." },
  "last_backup": { "key": "batchivo/2026/11/...sql.gz", "created_at": "...", "ok": true, "error": null } | null,
  "identity_missing": ["website_url"]
}
```

401 no token · 403 not owner.

### `POST /tenant/members/{member_id}/deactivate` — owner
### `POST /tenant/members/{member_id}/reactivate` — owner

```json
200 TenantMemberResponse (now with "is_active", "is_support")
```

401 no token · 403 not owner · 404 member not in this tenant · 409 target is an OWNER
(deactivate) · 422 malformed id. Each call writes an audit entry
(`member.deactivated` / `member.reactivated`).

## Changed endpoints

| Endpoint | Change |
|----------|--------|
| `GET /tenant/members` | items gain `is_active`, `is_support` |
| `POST /tenant/members/invite` | body gains optional `is_support: bool` (owner only; 403 otherwise) |
| `GET/PUT /settings/shop` | gains `website_url`, `email_from_address`, `email_from_name`, `orders_email`, `social_handle`, `sitemap_paths`; 422 on an un-normalisable URL or a sender address off the shop's domain |
| every authenticated route | 401 when the caller's membership in the token's tenant has `is_active = false` |

## Gated by deployment mode (single → 404, multi → unchanged)

Derived in the guard test from `app.routes`, not from this table:

- every route under `/platform/*` (tenant list/detail, impersonate, deactivate, reactivate,
  modules, audit), and any route depending on `get_platform_admin`;
- `GET /shop-resolver/tenant/{slug}/config`, `GET /shop-resolver/tenant/{slug}/exists`;
- `POST /onboarding/register`, `POST /onboarding/verify-email`,
  `POST /onboarding/resend-verification`.

`POST /auth/register` keeps returning 403 in both modes (unchanged).

## Resolved to the single shop in single mode

- every storefront route using `get_shop_tenant` / `ShopDB` (header `X-Shop-Hostname` accepted,
  not used for lookup);
- `GET /shop-resolver/resolve` returns the single tenant's configuration.

Zero tenants (before first-run): these routes answer 503 `"Instance not initialised"`.
