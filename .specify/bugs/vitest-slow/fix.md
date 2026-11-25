# Bug Fix: The Vitest unit suite takes three minutes

- **Slug**: vitest-slow
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Test files now share their worker (`isolate: false`): a worker builds jsdom and loads
`node_modules` once instead of once per file. `src/test/setup.ts` gives every file back what a
fresh worker gave it: application modules are re-evaluated against the file's own `vi.mock`
factories, and the globals, timers and `<body>` a previous file changed are restored. No test file
needed a change.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/vitest.config.ts` | modified | `isolate: false`, with the reason |
| `frontend/src/test/setup.ts` | modified | `vi.resetModules()` first; `afterAll` restores `SHARED_GLOBALS` (`location`, `localStorage`, `sessionStorage`, `fetch`, `crypto`, `matchMedia`, observers, `scrollTo`), real timers, stubbed globals, `<body>` |
| `frontend/src/test/shared-worker-stays-clean.test.ts` | added test | guards `isolate: false`, the reset coming before any import, and that every global a test file replaces is on the restore list |

## Measurements

Full `npx vitest run`, same machine (16 threads, 16 GB), nothing else running, `forks` pool,
`maxWorkers: '50%'`:

| Run | Wall | Vitest duration | Files | Tests |
|-----|------|-----------------|-------|-------|
| before 1 (cold) | 221 s | 186.3 s | 133 passed | 1540 passed |
| before 2 | 164 s | 103.4 s | 133 passed | 1540 passed |
| after 1 | 48 s | 42.9 s | 133 passed | 1540 passed |
| after 2 | 46 s | 40.9 s | 133 passed | 1540 passed |
| after + guard test | — | 36.9 s | 134 passed | 1549 passed (1540 + 9 guard) |

Setup time fell from 62–156 s cumulative to 9–12 s, import from 155–331 s to ~68 s.

## Options evaluated and not kept

- **Isolation off without the module reset**: on a 20-file sample, 20 of 130 tests failed. The
  application modules had been evaluated against the previous file's `vi.mock` factories.
  Vitest keeps mock registrations per file, but not evaluated modules.
- **`pool: 'threads'`** with the fix: 51.7 s against 41–43 s with forks. Kept forks.
- **`deps.optimizer.client`**: halved import time on the sample, but wall time did not move
  (51.6 → 48.9 / 50.4 s).
- **`happy-dom`**: not tried. It needs a new devDependency, which is outside this fix's scope
  (config, setup and test files only).
- **Barrel imports**: no single barrel dominates. Per `--experimental.importDurations.print`,
  `react-markdown` (~0.7 s) and app component graphs are the heaviest, with lucide and Radix spread
  across them.

## Verification

- `npx vitest run`: 134 files, 1549 tests passed.
- `npx vitest run --coverage`: 133 files, 1540 tests passed, thresholds met (statements 66%). Run
  before the guard test was added.
- `npm run lint`, `npm run typecheck`: clean.
