# Specification Quality Checklist: Pricing Engine Rebuild — Margins That Match Reality

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-11
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

Two items were failing on the first pass and were fixed before this checklist was marked complete:

1. **Implementation detail leak** — the clarification notes originally named storage shapes directly ("origin columns", "side table"). Rewritten in domain terms: provenance attached to each figure versus held in a shared register. The storage decision itself belongs to `/speckit-plan`.
2. **Scope boundary** — the source description did not state whether a solved price is published to connected channels. Resolved as a documented assumption (a solved price is a proposal; publishing is a separate operator action, out of scope) and as US4 acceptance scenario 5, rather than as a clarification marker.

Three judgement calls were made as documented assumptions rather than clarification markers, since each has a defensible default:

- **Margin denominator** — profit over the total the customer pays (item plus shipping revenue collected). This reproduces the 35.3% in the acceptance scenario and preserves today's definition. If the operator intends a net-revenue denominator instead, every reported percentage in this spec shifts, so this is the one assumption worth confirming explicitly.
- **Marketplace rates as fixtures** — entered, dated and owned by the operator, not maintained as a live schedule, since automatic ledger ingestion is a stated non-goal.
- **Reuse of existing foundations** — recursive bill of materials, per-channel price rows, packaging cost path, per-machine item configuration, printer records, production-run actuals, telemetry adapters.

Observations carried forward, not blockers for planning:

- `.specify/memory/constitution.md` is still the unfilled template, so no project principles constrained this spec. Given FR-047 through FR-052 are correctness requirements, filling it before `/speckit-plan` is worthwhile.
- FR-048 ("exactly one implementation of the cost calculation") and FR-050/FR-051 (migration deltas attributable per product) read as structural rather than user-facing. They are retained because the source description states them as correctness requirements and both are directly testable.
- US1 is a live-defect fix whose acceptance criterion is that reported costs **change**. Any plan or task breakdown must not treat an unchanged test suite as success for that story.
