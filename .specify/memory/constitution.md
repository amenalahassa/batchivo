# Batchivo Constitution

## Core Principles

### I. Multi-Tenant Isolation (NON-NEGOTIABLE)

Every table MUST carry `tenant_id`. No query MAY be written without tenant scope. Endpoints MUST
resolve the tenant through the `get_current_tenant` dependency, and tenant-scoped data MUST use the
`get_tenant_db` session dependency, never `get_db`, because PostgreSQL row-level security only
engages through the former. RLS is the enforcement layer; application-level filtering is a second
belt and MUST NOT be the only one.

**Why**: a leak across tenants is unrecoverable — it cannot be patched after the fact.

### II. Tests Are Part of the Change

All code MUST ship with tests. There is no exception and no "I'll add them after".

- A new endpoint MUST cover success, auth failure, validation failure and not-found.
- Business logic MUST cover the success path, edge cases and error conditions.
- A bug fix MUST carry a regression test that fails before the fix.
- A schema change MUST cover CRUD, relationships and constraints.
- `poetry run pytest` and `poetry run ruff check` MUST pass before a commit; frontend changes MUST
  additionally pass `npm test`, `npm run lint` and `npm run typecheck` -- CI runs the typecheck, so
  a type error found there is a red pipeline every change must wait behind.

**Why**: this project's own history shows the costly defects are the quiet ones — a wrong number
that raises no error.

### III. One Authoritative Implementation Per Calculation

A domain calculation MUST exist once. A second, parallel implementation is a defect regardless of
whether its output currently agrees, and it MUST be removed rather than kept in sync. Business logic
MUST live in a service under `backend/app/services/`; route handlers MUST stay thin and MUST NOT
re-derive what a service already computes.

**Why**: the costing engine carried two implementations — one in the service layer, one on the
model, with different labor rates — and they diverged silently.

### IV. Money Is Exact, and Settings Are Honoured

Monetary and rate values MUST use exact decimal arithmetic end to end. Binary floating point is NOT
acceptable in costing or pricing code, and rounding MUST occur only for display, never between
intermediate steps. A value the operator configured MUST be the value the system uses: a hardcoded
default silently shadowing a tenant setting is a defect, not a fallback.

**Why**: margin errors compound, and a figure nobody configured is a figure nobody can trust.

### V. Derived Figures Expire With Their Inputs

A cached or derived figure MUST NOT be served after any input beneath it has changed, including
transitively through nested bills of materials. Recomputing on demand is the default. A stored
derived figure MAY be introduced only together with the invalidation that keeps it honest, in the
same change.

**Why**: a stale derived figure produces a confidently wrong answer and raises no error, which makes
it the most damaging failure this system can have.

### VI. History Is Immutable, Provenance Is Visible

Values captured at the moment of a business event — a sale, a completed production run — MUST be
written once and MUST NOT be recomputed. Changing a rate, a price or a rule MUST NOT restate a
settled record. Any figure that drives a decision MUST carry where it came from and when it was set
or observed, so a reader knows how much to trust it.

**Why**: a margin trend that silently re-derives itself from today's inputs is not history, it is
fiction.

### VII. Deployment Goes Through The Pipeline (NON-NEGOTIABLE)

Changes MUST reach production exactly one way: push to `main`, Woodpecker CI builds and pushes
images, ArgoCD syncs. Docker images MUST NOT be built or pushed by hand. `kubectl apply` MUST NOT be
run directly against a cluster. Commits MUST follow `type: description` and MUST NOT carry AI markers
or Co-Authored-By trailers.

**Why**: a manual deploy leaves the declared state and the running state disagreeing, and the next
sync silently reverts it.

## Additional Constraints

The stack is fixed for existing surfaces and MUST NOT be substituted without an amendment:

- Backend: FastAPI with async SQLAlchemy 2.0 over PostgreSQL.
- Frontend: React with TypeScript, TanStack Query and shadcn/ui.
- Delivery: k3s with ArgoCD, behind a Cloudflare Tunnel.

Database changes MUST go through Alembic migrations, and a fresh database MUST be able to reach head
after every migration lands. Secrets MUST live in Kubernetes secrets and MUST NOT be committed to the
repository. A migration that changes computed values MUST report the per-record difference before the
change is accepted.

## Development Workflow

Work proceeds directly on `main`. Specifications and plans live under `specs/` via Spec Kit, and a
clarification pass MUST precede planning whenever a specification carries open decisions. Reviews
MUST verify compliance with these principles; complexity that violates one MUST be justified in
writing or removed. A test suite that turns green by restoring a defect is a failed change, not a
passing one.

## Governance

This constitution supersedes conflicting practice.

Amendments require a written rationale, a version bump, and a note of what must change in existing
code to comply. Version increments follow semantic versioning:

- **MAJOR**: a principle is removed or redefined in a backward-incompatible way.
- **MINOR**: a principle or section is added, or guidance is materially expanded.
- **PATCH**: clarifications, wording and typo fixes with no change of meaning.

`CLAUDE.md` remains the day-to-day operational guide and MUST NOT contradict this document. Where it
does, this document wins and `CLAUDE.md` MUST be corrected.

**Version**: 1.0.0 | **Ratified**: 2026-10-11 | **Last Amended**: 2026-10-11
