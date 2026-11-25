# Bug Assessment: Customer emails and discount/refund messages hardcode the pound sign

- **Slug**: hardcoded-gbp-emails-messages
- **Created**: 2026-11-03
- **Source**: pasted text (local bugcap #57; related user report bugcap #47)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

bugcap #57 (code review): the tenant's currency is ignored in the order confirmation email, the return-completed email, the shop discount messages and the refund messages, which all print `£`. The earlier `hardcoded-gbp-outside-pricing` fix did not cover these.

bugcap #47 (user, related): "some currency symbol is not aligned with that is configured in user settings" (Sales Channel Pricing screen).

## Symptom

A tenant whose currency is EUR or USD sends customers an order confirmation and a return/refund email with every amount prefixed `£`, and the shop shows "Discount applied: £5.00 off". Expected: the tenant's own symbol (`tenant.currency_symbol` / `currency_code`).

## Reproduction

1. Settings → set the tenant currency to EUR (€).
2. Place a shop order (or call `POST /api/v1/test/...` order-confirmation test route).
3. The confirmation email shows `£` on each line, subtotal, shipping and total.
4. In the shop, apply a discount code: the message reads `Discount applied: £… off`; with a minimum order amount, `Minimum order amount of £… required`.
5. Refund an order above its total: `Refund amount £… exceeds order total £…`; a successful refund reports `(£…)`.

## Suspected Code Paths

- `backend/app/services/email_service.py:168` `send_order_confirmation` — no currency parameter; `£` at `:219` (item price), `:282` (subtotal), `:286` (shipping), `:290` (total).
- `backend/app/services/email_service.py:1383` `send_return_completed` — `£` at `:1418`. By contrast `send_refund_confirmation` (`:324-353`) already takes `currency` and maps it to a symbol.
- Callers that have the tenant in hand but pass no currency: `api/v1/shop.py:1674`, `api/v1/payments.py:213,516`, `api/v1/orders.py:1555`, `api/v1/returns.py:468`, `api/v1/test.py:44`.
- `backend/app/api/v1/discounts.py:341,362` — `validate_discount_code` has `tenant` (`:256`) but formats `£`.
- `backend/app/api/v1/orders.py:1326,1423` — refund error and success messages.
- `backend/app/services/shipping_service.py:484` — `(+£3 remote area)`; this is the UK Highlands & Islands surcharge (`HIGHLAND_ISLAND_SURCHARGE_PENCE`), so `£` is probably correct there — low priority / likely intended.

## Root Cause Hypothesis

These strings predate multi-currency tenants and were written for the UK shop. The `hardcoded-gbp-outside-pricing` fix targeted the pricing and admin screens, not customer-facing emails and messages. Confidence: **high**.

## Proposed Remediation

**Preferred**: thread the tenant currency into these formatters. Add a single helper (e.g. `format_money(amount: Decimal, tenant) -> str` in an existing money/formatting module, reusing whatever `send_refund_confirmation` and the pricing fix use for the code→symbol mapping) and use it in: `send_order_confirmation` and `send_return_completed` (new `currency_symbol`/`currency` argument, defaulting to GBP for backward compatibility; every caller passes the tenant's), `discounts.py` messages and `orders.py` refund messages. Leave the UK-specific shipping surcharge text alone, or derive it from the same helper if the shipping service is ever used outside the UK.

**Alternatives**:
- Pass `currency_code` and map to a symbol inside `EmailService` (as `send_refund_confirmation` does). Keeps call sites simple, but duplicates the code→symbol table; the tenant already stores its own symbol.

**Files likely to change**:
- `backend/app/services/email_service.py`
- `backend/app/api/v1/{shop,payments,orders,returns,test,discounts}.py`
- `backend/tests/unit/test_email_service.py`, `backend/tests/api/test_discounts.py`, refund tests in `backend/tests/api/` or `tests/integration/`

**Tests to add or update**:
- Order confirmation and return-completed emails for a EUR tenant contain `€` and no `£`.
- Discount validation message for a USD tenant uses `$`.
- Refund over-total error for a EUR tenant uses `€`.
- GBP tenant output is unchanged (regression).

## Risks & Considerations

- Amounts must stay `Decimal` and be formatted at the edge (Constitution: money is exact); the helper must not go through `float`.
- Some currencies place the symbol after the amount or use different decimals; out of scope unless the tenant settings already model it — keep "symbol + 2 decimals" unless `currency_code` dictates otherwise.
- Email HTML snapshot tests (if any) will need updating.

## Open Questions

- [NEEDS CLARIFICATION: is bugcap #47 (Sales Channel Pricing screen) the same defect on the frontend? It is a separate screen and should get its own assessment if confirmed.]
