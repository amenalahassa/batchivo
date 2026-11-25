# Contracts — Background Jobs, Telemetry and the Rate Adapter

**Feature**: 002-pricing-engine-rebuild | **Date**: 2026-10-11 | **Tier**: 3 (rate adapter) and 4 (the rest)

Three contracts that are not request/response CRUD: the scenario job surface, the inbound telemetry port, and the outbound exchange-rate port. Each is stated as the boundary, not the implementation.

---

## Scenario runs (Tier 4)

### `POST /scenarios` — **member**

Body: `shock` (the overrides to apply — for example `{"material_cost_pct": 20, "fee_rate_pct_delta": 1}`), `margin_floor_pct`, optional `channel_id`.

Response `202 Accepted` with `{ id, state: "queued" }` — immediately, before any calculation (FR-044a).

### `GET /scenarios/{id}`

Response `200`: `state` (`queued`, `running`, `succeeded`, `partial`, `failed`), the `shock` and `inputs` the run used (FR-044c), and when finished the products below the floor with their before-and-after margins. A `partial` or `failed` run reports what it got and why it stopped — it never presents an incomplete list as complete (FR-044b).

### `GET /scenarios` — history, most recent first

**Invariants**: a scenario job writes no cost, price or provenance figure (FR-044d). Catalogue size changes duration, never success (FR-044e). A result read days later is labelled with its inputs so it cannot be mistaken for current figures.

**Execution**: a Celery task against the Redis broker already configured in `backend/app/config.py`, with state and result in `scenario_runs` so a worker restart does not lose a job. Requires the worker deployment manifest and a broker URL that resolves to the cluster Redis service rather than the configured `localhost` default (research D4).

---

## Telemetry ingestion port (Tier 4)

Inbound, read-only — the system never controls a printer (a stated non-goal).

**Port**: the existing `printer_adapter.Protocol`, already satisfied by `bambu_mqtt` and `moonraker_adapter` without explicit inheritance. Ingestion consumes it; no new adapter interface is introduced.

**What is written**: `actual_grams` and `actual_print_hours` onto the production run, with 3MF metadata as the fallback source when telemetry is silent. A smart-plug reading updates `printers.measured_watts` with `source = 'observed'`.

**What is never written**: an operator decision, whatever the reading (FR-042g). A policy field is not a measurement.

**Contract on arrival**: an observed value enters the variance engine, which either updates the estimate as a rolling average once the minimum number of outcomes is reached (FR-042a), or holds a proposal when it diverges beyond the operator's threshold (FR-042b). Applying an update sets the figure's origin to observed with its date and the outcomes it came from (FR-042f).

**Failure modes**: a printer that is offline produces no reading and no estimate change — silence is not a zero. An implausible reading is caught by the divergence threshold rather than by a sanity range, so one bad sensor cannot move a price.

---

## Exchange-rate port (Tier 3)

**Port**: one narrow interface — given a currency pair and a date, return a rate or report unavailable. The pricing code knows only the rate and its origin label (research D5).

**Behaviour required of any adapter**:

| Situation | Required behaviour | Requirement |
|---|---|---|
| Rate available | Fetch once, reuse for further sales the same day, freeze onto the order at sale | FR-028f |
| Service unreachable | Use the most recent known rate and show the date it was obtained | FR-028g |
| Operator supplies a rate | Override the fetched rate, recorded with its own origin | FR-028h |
| Anything at all | Never block the sale | FR-028i |
| No rate ever fetched for the pair | Ask the operator; never imply 1:1 | Edge case |
| A better rate appears later | Leave the frozen rate alone; report a variance, not a correction | FR-028j |

**Default provider**: a no-key ECB-backed endpoint publishing once per business day, which is why the day-reuse rule fits naturally. Availability and pair coverage (CAD, GBP, USD, EUR) are confirmed at implementation time; the port keeps a provider swap to one adapter.

**Testing**: `respx` stubs the provider, including the unreachable case, the stale-fallback case and the never-fetched case. No test reaches the network.
