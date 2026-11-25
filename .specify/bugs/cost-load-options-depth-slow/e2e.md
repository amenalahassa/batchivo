# Bug E2E Run: Loading one product's cost tree costs about a second of CPU

- **Slug**: cost-load-options-depth-slow
- **Run**: 2026-11-24
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The scenario journey and the three that were flaky pass; product-page journeys dropped from 9-15 s to 5-9 s each. Two consecutive full runs of the pricing project are green.

## Checks Performed

| Spec file | Command | Result | Notes |
|-----------|---------|--------|-------|
| `frontend/e2e/pricing/scenario.spec.ts` | `PLAYWRIGHT_BASE_URL=http://localhost:5183 PLAYWRIGHT_API_URL=http://localhost:8010 npx playwright test e2e/pricing/ --project=pricing --reporter=list --retries=0` | pass | passes 9 and 10, both 20/20 |
| `frontend/e2e/pricing/cost-and-margin.spec.ts` | `PLAYWRIGHT_BASE_URL=http://localhost:5183 PLAYWRIGHT_API_URL=http://localhost:8010 npx playwright test e2e/pricing/ --project=pricing --reporter=list --retries=0` | pass | passes 9 and 10, both 20/20 |
| `frontend/e2e/pricing/history-and-tiers.spec.ts` | `PLAYWRIGHT_BASE_URL=http://localhost:5183 PLAYWRIGHT_API_URL=http://localhost:8010 npx playwright test e2e/pricing/ --project=pricing --reporter=list --retries=0` | pass | passes 9 and 10, both 20/20 |
| `frontend/e2e/pricing/price-finder.spec.ts` | `PLAYWRIGHT_BASE_URL=http://localhost:5183 PLAYWRIGHT_API_URL=http://localhost:8010 npx playwright test e2e/pricing/ --project=pricing --reporter=list --retries=0` | pass | passes 9 and 10, both 20/20 |

Isolated stack: backend 8010 and Celery worker on a scratch PostgreSQL (5436) and Redis, Vite 5183, `seed_e2e.py` tenant re-seeded on a fresh database before each pass (as CI does).

## Output Excerpt

```
=== run 9
  20 passed (1.2m)
=== run 10
  20 passed (1.3m)
```

## Recommendation

Fix confirmed by the journeys above; close the bug.
