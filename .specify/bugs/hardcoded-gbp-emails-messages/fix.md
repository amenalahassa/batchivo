# Bug Fix: Customer emails and discount/refund messages hardcode the pound sign

- **Slug**: hardcoded-gbp-emails-messages
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

`send_order_confirmation` and `send_return_completed` take a `currency_symbol` (default `£`, so existing callers and GBP tenants are unchanged); every caller passes the tenant's `currency_symbol`. The shop discount messages and the refund messages use the tenant's symbol. Amounts stay `Decimal`, formatted once at the edge.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/services/email_service.py` | modified | `currency_symbol` on order confirmation (items, subtotal, shipping, total) and return completed |
| `backend/app/api/v1/shop.py`, `payments.py` (×2) | modified | pass `shop_tenant.currency_symbol` |
| `backend/app/api/v1/orders.py` | modified | resend confirmation passes the tenant symbol; refund refusal and success messages use it |
| `backend/app/api/v1/returns.py` | modified | return completed passes the tenant symbol |
| `backend/app/api/v1/discounts.py` | modified | "Minimum order amount…" and "Discount applied…" use the tenant symbol |
| `backend/tests/unit/test_email_service.py` | added tests | |
| `backend/tests/api/test_discounts.py` | added test | |
| `backend/tests/unit/test_orders_refund.py` | added test | |

## Tests Added or Updated

- `test_email_service.py::TestEmailsUseTheTenantCurrency` — EUR order confirmation has `€` and no `£`; default stays `£`; return completed in `$`.
- `test_discounts.py::test_validate_discount_messages_use_the_tenant_currency` — both messages in `€`.
- `test_orders_refund.py::...::test_refund_refusal_names_amounts_in_the_tenant_currency`.

## Local Verification

- `poetry run pytest tests/unit/test_email_service.py tests/api/test_discounts.py tests/unit/test_orders_refund.py` → passed.
- With `email_service.py` and `discounts.py` stashed → 3 of the 4 new email/discount tests fail (the default-£ test passes either way, as intended).

## Deviations from Assessment

- No new shared `format_money` helper: the tenant already stores its symbol, so callers pass `tenant.currency_symbol` and the templates keep their existing `:.2f` formatting. Smaller change, same result.
- `services/shipping_service.py:484` (`+£3 remote area`) left unchanged: it is the UK Highlands & Islands surcharge, as the assessment noted.
- `test.py` (dev-only test email route) not changed; it uses the `£` default.

## Follow-ups

- bugcap #47 (Sales Channel Pricing screen symbol) is a separate frontend screen and still needs its own assessment.
