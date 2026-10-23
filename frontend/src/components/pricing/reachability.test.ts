/**
 * @vitest-environment node
 *
 * No DOM here, so no jsdom. Building one costs more than this file's tests
 * take to run, and a budget spent before a test starts is what made the suite
 * depend on how loaded the machine was (task T174, Constitution II).
 */
/**
 * Every pricing surface has a way in (tasks T127–T133).
 *
 * This feature's components were each built and unit-tested, and eight of them
 * were imported by nothing at all. The tests passed, `tsc` passed, the lint
 * passed — and `CostBreakdownPanel`, `PriceSolverPanel`, `PriceLadder`,
 * `EstimateProposalList`, `ScenarioRunPanel`, `PrinterCostPolicyForm`,
 * `PricingPolicySettings` and `FilamentPurchaseForm` could not be opened by an
 * operator. US1's opening line is "the operator sets an hourly labor rate in
 * settings", and there was no screen on which to set one.
 *
 * A component rendered nowhere is the quiet defect this project's constitution
 * warns about: no error, no failing assertion, and a requirement that reads as
 * met. So the check is structural — does anything import it, and does that
 * chain reach a routed page — rather than another render test.
 *
 * Adding a pricing component means giving it a consumer. If it is genuinely
 * internal to another component in the same folder, importing it from there is
 * enough; this only refuses a component nothing references.
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..', '..')

/** Source files, test files excluded — a test is not a consumer. */
function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      out.push(...sourceFiles(full))
      continue
    }
    if (!/\.(ts|tsx)$/.test(entry.name)) continue
    if (/\.test\.(ts|tsx)$/.test(entry.name)) continue
    if (/\.stories\.(ts|tsx)$/.test(entry.name)) continue
    out.push(full)
  }
  return out
}

/** Read once: re-reading the tree per case made the suite time out. */
const ALL_SOURCES: ReadonlyArray<{ path: string; text: string }> = sourceFiles(SRC).map(
  (path) => ({ path, text: readFileSync(path, 'utf8') })
)

/** The files that mention `name` as an imported identifier, excluding itself. */
function consumersOf(name: string, ownPath: string): string[] {
  const pattern = new RegExp(`\\b${name}\\b`)
  return ALL_SOURCES.filter(
    ({ path, text }) => path !== ownPath && pattern.test(text)
  ).map(({ path }) => relative(SRC, path))
}

/**
 * Components the operator must be able to reach, and the requirement that
 * says so. Named explicitly rather than globbed, so that deleting a screen is
 * a deliberate edit to this list and not a silently passing test.
 */
const SURFACES: ReadonlyArray<{ file: string; component: string; why: string }> = [
  {
    file: 'components/pricing/CostBreakdownPanel.tsx',
    component: 'CostBreakdownPanel',
    why: 'FR-018/FR-046/SC-004 — every line itemised with its origin, and the observed share',
  },
  {
    file: 'components/pricing/CostBreakdownSection.tsx',
    component: 'CostBreakdownSection',
    why: 'the fetching wrapper the product and model pages mount',
  },
  {
    file: 'components/pricing/PriceSolverPanel.tsx',
    component: 'PriceSolverPanel',
    why: 'FR-032/SC-005 — a target margin returns a price in one request',
  },
  {
    file: 'components/pricing/PriceLadder.tsx',
    component: 'PriceLadder',
    why: 'FR-007 — a market judgement is made from a ladder, never stored as one number',
  },
  {
    file: 'components/pricing/EstimateProposalList.tsx',
    component: 'EstimateProposalList',
    why: 'FR-042c — a held proposal is acceptable or rejectable as a whole',
  },
  {
    file: 'components/pricing/ScenarioRunPanel.tsx',
    component: 'ScenarioRunPanel',
    why: 'FR-044/SC-006 — a catalogue shock requested in a single action',
  },
  {
    file: 'components/pricing/FeeBreakdownTable.tsx',
    component: 'FeeBreakdownTable',
    why: 'FR-021c — a capped fee is never mistaken for a miscalculated one',
  },
  {
    file: 'components/pricing/MarginDivergencePanel.tsx',
    component: 'MarginDivergencePanel',
    why: 'FR-042/US7 scenario 3 — the operator is told which lines moved, not only that one did',
  },
  {
    file: 'components/pricing/ChannelReconciliation.tsx',
    component: 'ChannelReconciliation',
    why: 'FR-041d — planned against recorded, with the unallocated remainder',
  },
  {
    file: 'components/printers/PrinterCostPolicyForm.tsx',
    component: 'PrinterCostPolicyForm',
    why: 'FR-010/FR-011 — the hourly rate is settable per machine',
  },
  {
    file: 'components/settings/PricingPolicySettings.tsx',
    component: 'PricingPolicySettings',
    why: 'FR-002/FR-031 — the operator sets the labour rate and the margin basis',
  },
  {
    file: 'components/filaments/FilamentPurchaseForm.tsx',
    component: 'FilamentPurchaseForm',
    why: 'FR-008a — a purchase is recordable, so a landed cost can be derived',
  },
]

describe('pricing surfaces are reachable', () => {
  it.each(SURFACES)('$component is imported by something ($why)', ({ file, component }) => {
    const consumers = consumersOf(component, join(SRC, ...file.split('/')))

    expect(
      consumers,
      `${component} is referenced by no source file, so an operator cannot open it`
    ).not.toHaveLength(0)
  })

  it('the pages that mount them are in the router', () => {
    // A page component that no route renders is the same defect one level up.
    const app = readFileSync(join(SRC, 'App.tsx'), 'utf8')

    for (const page of ['Scenarios', 'Settings', 'Printers', 'FilamentLibrary']) {
      expect(app, `${page} is not routed, so what it mounts is unreachable`).toContain(
        `@/pages/${page}`
      )
    }
  })
})
