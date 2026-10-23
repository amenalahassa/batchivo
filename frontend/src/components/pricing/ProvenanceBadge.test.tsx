/**
 * Tests for the provenance badge, the observed share and the stale warning (T107a)
 *
 * What these guard, and the wrong answer each one prevents:
 *
 * - **Every figure names its origin** (FR-001). A cost line with no label
 *   reads as authoritative, and the default — a figure nobody measured or set
 *   — is the one most likely to be wrong.
 * - **A stale measurement is flagged and still shown** (FR-005). Hiding it
 *   leaves the cost unexplained; showing it unflagged leaves a three-year-old
 *   reading looking current. The test below checks *both* at once, because
 *   each alone passes a broken implementation.
 * - **Only measurements go stale.** A decision does not expire and an observed
 *   figure is refreshed from its source, so flagging either is noise that
 *   trains the reader to ignore the flag.
 * - **A pending proposal says that pricing still uses the current figure**
 *   (FR-042e). Without it a reader cannot tell whether they are approving a
 *   change or undoing one that already happened.
 * - **Rejecting is not a veto on the field** (FR-042d). Somebody who believes
 *   it silences the figure for ever will accept a bad reading rather than lose
 *   the alert.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ProvenanceBadge } from './ProvenanceBadge'
import { EstimateProposalList } from './EstimateProposalList'
import { CostBreakdownPanel } from './CostBreakdownPanel'
import { isStaleMeasurement } from '@/lib/provenance'
import * as pricingApi from '@/lib/api/pricing'
import type { CostBreakdown, CostLine, EstimateRevision } from '@/types/pricing'

vi.mock('@/lib/api/pricing', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/pricing')>(
    '@/lib/api/pricing',
  )
  return {
    ...actual,
    listEstimateRevisions: vi.fn(),
    acceptEstimateRevision: vi.fn(),
    rejectEstimateRevision: vi.fn(),
  }
})

const DAY = 86_400_000

function daysAgo(days: number): string {
  return new Date(Date.now() - days * DAY).toISOString().slice(0, 10)
}

function line(overrides: Partial<CostLine> = {}): CostLine {
  return {
    key: 'material',
    label: 'Filament',
    amount: '4.34',
    risk_class: 'at_risk',
    source: 'measured',
    as_of: daysAgo(2),
    has_pending_revision: false,
    ...overrides,
  }
}

function breakdown(overrides: Partial<CostBreakdown> = {}): CostBreakdown {
  return {
    lines: [line()],
    at_risk_subtotal: '4.34',
    not_at_risk_subtotal: '0.92',
    yield_applied: '0.92',
    failure_mode: 'per_part',
    failure_premium: '0.38',
    total_make_cost: '20.30',
    observed_share: '0.7',
    assumed_share: '0.3',
    incomplete_reasons: [],
    ...overrides,
  } as CostBreakdown
}

function revision(overrides: Partial<EstimateRevision> = {}): EstimateRevision {
  return {
    id: 'rev-1',
    entity_type: 'model',
    entity_id: 'model-1',
    field_name: 'print_time_minutes',
    current_value: '100.000000',
    observed_value: '910.000000',
    divergence_pct: '810.0000',
    derived_from_run_ids: ['run-0', 'run-1', 'run-2'],
    state: 'pending',
    observed_as_of: '2026-10-10',
    reviewed_by_user_id: null,
    reviewed_at: null,
    created_at: '2026-10-10T00:00:00Z',
    ...overrides,
  }
}

function renderList(props: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <EstimateProposalList {...props} />
      </QueryClientProvider>,
    ),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
    revisions: [],
    total: 0,
    pending_count: 0,
  })
})

// ---------------------------------------------------------------------------
// The badge
// ---------------------------------------------------------------------------

describe('ProvenanceBadge', () => {
  it.each([
    ['observed', 'Observed'],
    ['measured', 'Measured'],
    ['policy', 'Your setting'],
    ['assumed', 'Assumed'],
  ] as const)('labels a %s figure as "%s"', (source, label) => {
    render(<ProvenanceBadge source={source} asOf="2026-10-01" />)

    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('calls a policy figure the operator\'s own setting, not "policy"', () => {
    // "Policy" sounds like something the software imposed; the operator chose
    // it, and that distinction is what FR-002 protects.
    render(<ProvenanceBadge source="policy" asOf="2026-10-01" />)

    expect(screen.getByText('Your setting')).toBeInTheDocument()
    expect(screen.queryByText(/^Policy$/)).not.toBeInTheDocument()
  })

  it('shows the date a figure was established', () => {
    render(<ProvenanceBadge source="measured" asOf="2026-10-01" />)

    expect(screen.getByText('as of 2026-10-01')).toBeInTheDocument()
  })

  it('says a figure was never recorded rather than leaving the date blank', () => {
    // A blank reads as missing data, where "no date" is itself the fact.
    render(<ProvenanceBadge source="assumed" asOf={null} isDefault />)

    expect(screen.getByText('never recorded')).toBeInTheDocument()
  })

  it('explains what each origin means on hover', () => {
    render(<ProvenanceBadge source="assumed" asOf={null} isDefault />)

    expect(screen.getByText('Assumed')).toHaveAttribute(
      'title',
      expect.stringContaining('may be wrong'),
    )
  })

  it('flags a stale measurement', () => {
    render(<ProvenanceBadge source="measured" asOf="2020-01-01" isStale />)

    expect(screen.getByTestId('provenance-stale')).toBeInTheDocument()
  })

  it('still shows the origin and the date alongside the stale flag', () => {
    // FR-005 in one assertion. An operator with an old number can judge it;
    // one with no number cannot.
    render(<ProvenanceBadge source="measured" asOf="2020-01-01" isStale />)

    expect(screen.getByText('Measured')).toBeInTheDocument()
    expect(screen.getByText('as of 2020-01-01')).toBeInTheDocument()
    expect(screen.getByTestId('provenance-stale')).toBeInTheDocument()
  })

  it('says the stale figure is still in use', () => {
    render(<ProvenanceBadge source="measured" asOf="2020-01-01" isStale />)

    expect(screen.getByTestId('provenance-stale')).toHaveAttribute(
      'title',
      expect.stringContaining('still in use'),
    )
  })

  it('does not flag a fresh measurement', () => {
    render(<ProvenanceBadge source="measured" asOf={daysAgo(1)} />)

    expect(screen.queryByTestId('provenance-stale')).not.toBeInTheDocument()
  })

  it('flags a figure with a pending revision', () => {
    render(<ProvenanceBadge source="measured" asOf="2026-10-01" hasPendingRevision />)

    expect(screen.getByTestId('provenance-pending-revision')).toBeInTheDocument()
  })

  it('says pricing still uses the current figure while a revision is pending', () => {
    // FR-042e. Without this a reader cannot tell whether the new reading is
    // already in use.
    render(<ProvenanceBadge source="measured" asOf="2026-10-01" hasPendingRevision />)

    expect(screen.getByTestId('provenance-pending-revision')).toHaveAttribute(
      'title',
      expect.stringContaining('still uses the current figure'),
    )
  })

  it('drops the date in compact mode but keeps the origin', () => {
    render(<ProvenanceBadge source="assumed" asOf="2026-10-01" compact />)

    expect(screen.getByText('Assumed')).toBeInTheDocument()
    expect(screen.queryByText('as of 2026-10-01')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Staleness, as a rule rather than as a rendering
// ---------------------------------------------------------------------------

describe('isStaleMeasurement', () => {
  it('is stale past the threshold', () => {
    expect(isStaleMeasurement(line({ as_of: daysAgo(200) }), 180)).toBe(true)
  })

  it('is not stale at exactly the threshold', () => {
    // The operator who sets 180 days means "up to 180 is fine".
    expect(isStaleMeasurement(line({ as_of: daysAgo(180) }), 180)).toBe(false)
  })

  it('is stale one day past the threshold', () => {
    expect(isStaleMeasurement(line({ as_of: daysAgo(181) }), 180)).toBe(true)
  })

  it.each(['observed', 'policy', 'assumed'] as const)(
    'never flags a %s figure, however old',
    (source) => {
      // A decision does not expire and an observed figure is refreshed from
      // its source. Flagging either is noise.
      expect(isStaleMeasurement(line({ source, as_of: daysAgo(4000) }), 180)).toBe(false)
    },
  )

  it('does not flag a figure with no date as stale', () => {
    // "Nobody recorded this" is a different fact, carried by the origin.
    // Calling it stale would tell the operator to re-measure something they
    // never measured.
    expect(isStaleMeasurement(line({ as_of: null }), 180)).toBe(false)
  })

  it('does not flag anything when no threshold is set', () => {
    // Inventing one would flag figures against a number the operator never
    // chose, and FR-005 makes the threshold theirs.
    expect(isStaleMeasurement(line({ as_of: daysAgo(4000) }), null)).toBe(false)
    expect(isStaleMeasurement(line({ as_of: daysAgo(4000) }), undefined)).toBe(false)
  })

  it('does not throw on an unparseable date', () => {
    expect(isStaleMeasurement(line({ as_of: 'last tuesday' }), 180)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// The breakdown panel: observed share and stale warning
// ---------------------------------------------------------------------------

describe('CostBreakdownPanel provenance', () => {
  it('reports the observed share against the assumed share', () => {
    // SC-010 measures this share, so it is on the screen rather than implied.
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(screen.getByText(/70(\.0)?%/)).toBeInTheDocument()
    expect(screen.getByText(/30(\.0)?%/)).toBeInTheDocument()
  })

  it('labels every cost line with its origin', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [
            line({ key: 'material', label: 'Filament', source: 'measured' }),
            line({ key: 'machine', label: 'Machine time', source: 'observed' }),
            line({ key: 'overhead', label: 'Overhead', source: 'assumed', as_of: null }),
          ],
        })}
      />,
    )

    expect(screen.getByText('Measured')).toBeInTheDocument()
    expect(screen.getByText('Observed')).toBeInTheDocument()
    expect(screen.getByText('Assumed')).toBeInTheDocument()
  })

  it('warns when a measurement is past the threshold', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [line({ label: 'Filament', as_of: daysAgo(400) })],
        })}
        stalenessThresholdDays={180}
      />,
    )

    expect(screen.getByTestId('stale-measurements')).toBeInTheDocument()
  })

  it('names which figures to re-measure rather than only counting them', () => {
    // "2 figures are stale" sends the reader hunting; the point of the warning
    // is to say what to re-measure.
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [
            line({ key: 'material', label: 'Filament', as_of: daysAgo(400) }),
            line({ key: 'machine', label: 'Machine time', as_of: daysAgo(400) }),
          ],
        })}
        stalenessThresholdDays={180}
      />,
    )

    const warning = screen.getByTestId('stale-measurements')
    expect(warning.textContent).toContain('Filament')
    expect(warning.textContent).toContain('Machine time')
  })

  it('still shows the amount of a stale line', () => {
    // The other half of FR-005, checked on the panel and not only the badge.
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [line({ label: 'Filament', amount: '4.34', as_of: daysAgo(400) })],
        })}
        stalenessThresholdDays={180}
      />,
    )

    const row = screen.getByTestId('cost-line-material')
    expect(within(row).getByText(/4\.34/)).toBeInTheDocument()
  })

  it('reports the threshold so the warning can be judged', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({ lines: [line({ as_of: daysAgo(400) })] })}
        stalenessThresholdDays={180}
      />,
    )

    expect(screen.getByTestId('stale-measurements').textContent).toContain('180 days')
  })

  it('does not warn when no threshold is given', () => {
    render(
      <CostBreakdownPanel breakdown={breakdown({ lines: [line({ as_of: daysAgo(4000) })] })} />,
    )

    expect(screen.queryByTestId('stale-measurements')).not.toBeInTheDocument()
  })

  it('does not warn about an old observed figure', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [line({ source: 'observed', as_of: daysAgo(4000) })],
        })}
        stalenessThresholdDays={180}
      />,
    )

    expect(screen.queryByTestId('stale-measurements')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// The proposal list
// ---------------------------------------------------------------------------

describe('EstimateProposalList', () => {
  it('says nothing is waiting when nothing is', async () => {
    renderList()

    expect(await screen.findByTestId('no-proposals')).toBeInTheDocument()
  })

  it('explains that an agreeing observation updates the figure on its own', async () => {
    // Otherwise an empty list reads as "the mechanism is not working".
    renderList()

    await screen.findByTestId('no-proposals')
    expect(screen.getByText(/updates on its own/i)).toBeInTheDocument()
  })

  it('states the current estimate, the observation and the gap', async () => {
    // FR-042c, item by item.
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    renderList()

    expect(await screen.findByTestId('proposal-current')).toHaveTextContent('100')
    expect(screen.getByTestId('proposal-observed')).toHaveTextContent('910')
    expect(screen.getByTestId('proposal-divergence')).toHaveTextContent('810.0% out')
  })

  it('keeps the exact divergence available even though it is shown rounded', async () => {
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision({ divergence_pct: '810.1234' })],
      total: 1,
      pending_count: 1,
    })
    renderList()

    const badge = await screen.findByTestId('proposal-divergence')
    expect(badge).toHaveTextContent('810.1% out')
    expect(badge).toHaveAttribute('title', expect.stringContaining('810.1234'))
  })

  it('says pricing still uses the current figure', async () => {
    // FR-042e. The single most important sentence on this screen.
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    renderList()

    expect(await screen.findByText(/Pricing still uses 100/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing changes until you accept/)).toBeInTheDocument()
  })

  it('lists the outcomes the proposal came from', async () => {
    // A reviewer who cannot see the readings is guessing.
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    renderList()

    const outcomes = await screen.findByTestId('proposal-outcomes')
    expect(within(outcomes).getByText('run-0')).toBeInTheDocument()
    expect(within(outcomes).getByText('run-2')).toBeInTheDocument()
  })

  it('reads a field name as words rather than as a column name', async () => {
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    renderList()

    expect(await screen.findByText('print time minutes')).toBeInTheDocument()
  })

  it('accepts a proposal whole', async () => {
    // No partial acceptance (FR-042c): half a proposal is a figure no
    // evidence supports.
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    vi.mocked(pricingApi.acceptEstimateRevision).mockResolvedValue(
      revision({ state: 'accepted' }),
    )
    const user = userEvent.setup({ delay: null })
    renderList()

    await user.click(await screen.findByRole('button', { name: /accept the observed/i }))

    await waitFor(() => {
      expect(pricingApi.acceptEstimateRevision).toHaveBeenCalledWith('rev-1')
    })
  })

  it('confirms before rejecting', async () => {
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    const user = userEvent.setup({ delay: null })
    renderList()

    await user.click(await screen.findByRole('button', { name: /reject the observed/i }))

    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    expect(pricingApi.rejectEstimateRevision).not.toHaveBeenCalled()
  })

  it('says that rejecting is not a veto on the field', async () => {
    // FR-042d. Somebody who believes it silences the figure for ever will
    // accept a bad reading rather than lose the alert.
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    const user = userEvent.setup({ delay: null })
    renderList()

    await user.click(await screen.findByRole('button', { name: /reject the observed/i }))
    const dialog = await screen.findByRole('alertdialog')

    expect(dialog.textContent).toMatch(/new recorded outcome can raise it/i)
    expect(dialog.textContent).toMatch(/not switching the alert off/i)
  })

  it('rejects once confirmed', async () => {
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    vi.mocked(pricingApi.rejectEstimateRevision).mockResolvedValue(
      revision({ state: 'rejected' }),
    )
    const user = userEvent.setup({ delay: null })
    renderList()

    await user.click(await screen.findByRole('button', { name: /reject the observed/i }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: /keep the current figure/i }))

    await waitFor(() => {
      expect(pricingApi.rejectEstimateRevision).toHaveBeenCalledWith('rev-1')
    })
  })

  it('invalidates the cost reads after an acceptance', async () => {
    // Accepting moves a figure, so every cost derived from it is now wrong.
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    vi.mocked(pricingApi.acceptEstimateRevision).mockResolvedValue(
      revision({ state: 'accepted' }),
    )
    const user = userEvent.setup({ delay: null })
    const { queryClient } = renderList()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(await screen.findByRole('button', { name: /accept the observed/i }))

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['cost-breakdown'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['provenance'] })
    })
  })

  it('reports a failed decision without pretending the figure moved', async () => {
    vi.mocked(pricingApi.listEstimateRevisions).mockResolvedValue({
      revisions: [revision()],
      total: 1,
      pending_count: 1,
    })
    vi.mocked(pricingApi.acceptEstimateRevision).mockRejectedValue(new Error('409'))
    const user = userEvent.setup({ delay: null })
    renderList()

    await user.click(await screen.findByRole('button', { name: /accept the observed/i }))

    expect(await screen.findByTestId('proposal-error')).toHaveTextContent(
      /figure is unchanged/i,
    )
  })

  it('says the figures are unchanged when the list itself cannot load', async () => {
    vi.mocked(pricingApi.listEstimateRevisions).mockRejectedValue(new Error('boom'))
    renderList()

    expect(await screen.findByTestId('estimate-proposals-error')).toHaveTextContent(
      /figures are unchanged/i,
    )
  })

  it('narrows to one record when asked', async () => {
    renderList({ entityType: 'model', entityId: 'model-1' })

    await waitFor(() => {
      expect(pricingApi.listEstimateRevisions).toHaveBeenCalledWith({
        state: 'pending',
        entityType: 'model',
        entityId: 'model-1',
      })
    })
  })
})
