# Quickstart: validating the Single-Tenant VPS Edition

Each section proves one story. Automated checks first, then the manual VPS run.

## 1. Automated (every change)

```bash
cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check
cd frontend && npm test && npm run lint && npm run typecheck
cd landing && node --test tests/
```

Expected: green, including
- `tests/guards/test_no_hardcoded_shop_identity.py` (FR-016),
- `tests/guards/test_mode_gated_routes.py` — derived from `app.routes`, both modes (FR-002–FR-008),
- `tests/unit/test_shop_identity.py` — a tenant named "Acme Prints" with `https://acme.example`
  never yields "mystmere" in any output from data-model §3 (SC-001),
- `tests/unit/test_commerce_order_ownership.py` — identifiers equal their pre-change values
  (SC-007),
- `tests/ops/` — init twice (second exits 4), backup run/prune/restore against moto S3,
  update script with a stubbed `docker` (success, backup failure → 5, migration failure → 6).

## 2. Story 2 — mode switch, locally

```bash
DEPLOYMENT_MODE=single poetry run uvicorn app.main:app
curl -s localhost:8000/api/v1/instance            # {"deployment_mode":"single",...}
curl -s -o /dev/null -w '%{http_code}' localhost:8000/api/v1/platform/tenants   # 404
curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8000/api/v1/onboarding/register  # 404
```

Restart with `DEPLOYMENT_MODE=multi`: the same calls behave as before (401/422 for the platform
route without a token, registration accepted).

## 3. Story 3 — install on a throwaway VPS

Prerequisites: a VPS with Docker + compose plugin, a domain `A` record pointing at it, an S3
bucket + key, a Resend key, a Harbor robot pull credential.

```bash
scp -r deploy/vps user@vps:~/batchivo && ssh user@vps
cd ~/batchivo && cp .env.example .env && $EDITOR .env
docker login registry.techize.co.uk
./batchivo install
./batchivo init --shop-name "Acme Prints" --owner-email owner@acme.example --support-email support@provider.example
```

Expected: valid certificate on `https://<domain>`; owner sets a password from the email and lands
on the onboarding wizard; `./batchivo init` again exits 4. Time it (SC-004 < 30 min).

## 4. Story 4 — update, failure, restore

```bash
./batchivo update v1.4.1          # OK update v1.4.0 -> v1.4.1
./batchivo update latest          # exit 2
```

Simulate a failing migration with a test release tag carrying a broken revision: exit 6, the
previous version runs again, the printed backup key exists in the bucket. On a second VPS:
`./batchivo install && ./batchivo restore <key>` → shop data present (SC-006).

## 5. Story 1 — identity on a running instance

Set Settings → Shop (name, website, sender, social handle), then check: product page link,
checkout (Square note and payment link name), confirmation redirect, order email (sender and
footer), CSV export vendor, Shopify sync vendor, sitemap base URL — all show the shop's values.
Unverified sender domain: banner on the dashboard, no email sent from another domain, order
still recorded.

## 6. Release on the project cluster (HandyLabs)

1. Before merging, the owner fills Settings → Shop for HandyLabs (name, website URL, sender
   address, social handle) on the current production.
2. Merge → pipeline → ArgoCD; the manifest sets `DEPLOYMENT_MODE: "single"` and no longer sets
   the Mystmere `SHOP_*` values.
3. Check `/api/v1/instance` = single, the dashboard shows no identity warning, the platform
   console is gone, and a re-sync of an existing WooCommerce order creates no duplicate.
