# Bug Assessment: The Vitest unit suite takes three minutes

- **Slug**: vitest-slow
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator session, from the user's question "why is vitest slow")
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> The frontend unit suite (`cd frontend && npm run test:run`, Vitest 4.1, ~1540 tests in 133
> files) takes ~170-200 s wall time on the 16-core / 16 GB Windows dev machine; cumulative
> environment 443 s, setup 218 s, import 300 s, tests 290 s. Per-file jsdom environment and
> module imports dominate. Test time is the bottleneck of every merge.

## Symptom

A full unit run spends most of its time before tests start: every DOM test file builds its own
jsdom and imports React, Radix, lucide, react-markdown and the app modules again. Expected: the
run is bounded by the tests themselves.

## Reproduction

1. `cd frontend && npm run test:run`
2. Read the `Duration` line: environment + import + setup exceed the test time.
3. Single file, warm cache: `npx vitest run src/App.test.tsx` → environment 1.58 s, tests 7 ms.
   Same file on a cold cache and a loaded machine: environment 27 s.

## Suspected Code Paths

- `frontend/vitest.config.ts` — default `isolate: true`: each of the 108 jsdom files gets a fresh
  worker context, so jsdom and every `node_modules` import are paid per file.
- `frontend/src/test/setup.ts` — runs per file; already lean (router mock without
  `importActual`, DOM-only imports guarded), not the main cost any more.
- Import breakdown on a 20-file sample (`--experimental.importDurations.print`): no single barrel
  dominates. The heaviest are `react-markdown` (~0.7 s) and app component graphs (0.8–1.5 s);
  lucide and Radix are spread across them.

## Root Cause Hypothesis

High confidence. 25 of 133 files already opt out of jsdom (`@vitest-environment node`), but the
other 108 each rebuild the environment and the module graph. With 8 workers on a memory-tight
machine, that work also contends, which inflates the cumulative environment time to 443 s.

## Proposed Remediation

**Preferred**: `isolate: false` in `vitest.config.ts`, so a worker builds jsdom and loads
`node_modules` once. Make up for what a fresh worker gave for free in `src/test/setup.ts`:
`vi.resetModules()` at the start of each file (application modules otherwise stay bound to the
previous file's `vi.mock` factories; Vitest already keeps mock registrations per file), and an
`afterAll` that restores the globals tests replace (`localStorage`, `sessionStorage`, `location`,
`fetch`…), real timers, stubbed globals and `<body>`.

Sample evidence (20 jsdom files, 2 workers): isolated 51.6 s; `--no-isolate` without the reset
20 tests fail (stale mocks across files); with the reset 21.2 s, 130/130 pass.

**Alternatives**:
- `happy-dom` instead of jsdom: cheaper environment, but needs a new devDependency and changes
  DOM semantics under ~1000 tests; out of this fix's allowed scope (config, setup and tests only).
- `deps.optimizer.client`: halves the measured import time on the sample, but wall time did not
  move (51.6 → 48.9/50.4 s); not worth the extra pre-bundling step.
- Leave `pool`/`maxWorkers` as they are unless the full-run measurement says otherwise.

**Files likely to change**:
- `frontend/vitest.config.ts`
- `frontend/src/test/setup.ts`

**Tests to add or update**:
- None new: the guard is that the same 133 files and the same test count still pass in a shared
  worker, including the files that replace globals (`lib/auth.test.ts`, `lib/utils.test.ts`),
  fake the clock (`ChannelProfitabilityPanel.test.tsx`) or unmock the router (`App.test.tsx`,
  `ModelForm.test.tsx`, `CreateRunWizard.test.tsx`).

## Risks & Considerations

- Order dependence: a future test that mutates a global not on the restore list could leak into
  the next file in the same worker. The restore list covers every global the suite replaces today.
- `test:ci` runs with coverage; `isolate: false` is supported by the v8 provider.

## Open Questions

- None.
