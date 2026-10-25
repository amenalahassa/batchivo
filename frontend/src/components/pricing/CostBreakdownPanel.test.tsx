/**
 * CostBreakdownPanel tests (task T055a).
 *
 * The panel's job is to make a figure checkable, so the tests assert the
 * things a reader needs rather than the markup: each line's amount, its risk
 * class, where it came from and when, what is missing, and — the one that
 * matters most — that a missing figure is never rendered as zero.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { CostBreakdownPanel } from './CostBreakdownPanel'
import type { CostBreakdown, CostLine } from '@/types/pricing'

function line(overrides: Partial<CostLine> = {}): CostLine {
  return {
    key: 'material',
    label: 'Filament in the part',
    amount: '4.52',
    risk_class: 'at_risk',
    source: 'observed',
    as_of: '2026-03-01',
    has_pending_revision: false,
    ...overrides,
  }
}

/** The golden case: a make cost of CA$20.30 at a 92% yield. */
function breakdown(overrides: Partial<CostBreakdown> = {}): CostBreakdown {
  return {
    lines: [
      line(),
      line({
        key: 'machine',
        label: 'Machine occupancy',
        amount: '2.21',
        source: 'measured',
        as_of: '2026-02-14',
      }),
      line({
        key: 'packaging',
        label: 'Packaging materials',
        amount: '0.92',
        risk_class: 'not_at_risk',
        source: 'assumed',
        as_of: null,
      }),
    ],
    at_risk_subtotal: '19.38',
    not_at_risk_subtotal: '0.92',
    yield_applied: '0.9200',
    failure_mode: 'per_part',
    failure_premium: '1.68',
    total_make_cost: '20.30',
    observed_share: '0.70',
    assumed_share: '0.30',
    incomplete_reasons: [],
    ...overrides,
  }
}

describe('CostBreakdownPanel', () => {
  it('renders the total make cost exactly as sent, cents and all', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)
    expect(screen.getByTestId('total-make-cost')).toHaveTextContent('$20.30')
  })

  it('renders every line with its amount', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(within(screen.getByTestId('cost-line-material')).getByText('$4.52')).toBeInTheDocument()
    expect(within(screen.getByTestId('cost-line-machine')).getByText('$2.21')).toBeInTheDocument()
    expect(
      within(screen.getByTestId('cost-line-packaging')).getByText('$0.92'),
    ).toBeInTheDocument()
  })

  it('names the risk class of each line', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(within(screen.getByTestId('cost-line-material')).getByText('At risk')).toBeInTheDocument()
    expect(
      within(screen.getByTestId('cost-line-packaging')).getByText('Not at risk'),
    ).toBeInTheDocument()
  })

  it('says how far to believe an observed line (T259)', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({ lines: [line({ confidence: '0.8333' })] })}
      />,
    )

    expect(screen.getByTestId('provenance-confidence')).toHaveTextContent('83% confidence')
  })

  it('claims no confidence for a line nobody observed', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({ lines: [line({ source: 'policy', confidence: null })] })}
      />,
    )

    expect(screen.queryByTestId('provenance-confidence')).not.toBeInTheDocument()
  })

  it('names where each line came from', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(within(screen.getByTestId('cost-line-material')).getByText('Observed')).toBeInTheDocument()
    expect(within(screen.getByTestId('cost-line-machine')).getByText('Measured')).toBeInTheDocument()
    expect(
      within(screen.getByTestId('cost-line-packaging')).getByText('Assumed'),
    ).toBeInTheDocument()
  })

  it('dates each line, and says so plainly when it has no date', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(
      within(screen.getByTestId('cost-line-material')).getByText('as of 2026-03-01'),
    ).toBeInTheDocument()
    expect(
      within(screen.getByTestId('cost-line-packaging')).getByText('never recorded'),
    ).toBeInTheDocument()
  })

  it('states the observed and assumed shares', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)
    expect(screen.getByText(/70% of this cost rests on observed/)).toBeInTheDocument()
    expect(screen.getByText(/30% is still assumed/)).toBeInTheDocument()
  })

  it('reports the subtotals and the failure premium', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(screen.getByTestId('at-risk-subtotal')).toHaveTextContent('$19.38')
    expect(screen.getByTestId('not-at-risk-subtotal')).toHaveTextContent('$0.92')
    expect(screen.getByTestId('failure-premium')).toHaveTextContent('$1.68')
    expect(screen.getByText(/92% yield/)).toBeInTheDocument()
  })

  it('names the failure mode, since per-plate and per-part differ', () => {
    render(<CostBreakdownPanel breakdown={breakdown({ failure_mode: 'per_plate' })} />)
    expect(screen.getByText('(per plate)')).toBeInTheDocument()
  })

  describe('an incompletely costed item', () => {
    const incomplete = breakdown({
      lines: [line()],
      incomplete_reasons: [
        'this printer has no cost policy, so no machine rate could be derived',
        'the item has no print time, so machine occupancy is unknown',
      ],
    })

    it('says it is incomplete rather than showing a total as if it were whole', () => {
      render(<CostBreakdownPanel breakdown={incomplete} />)

      const warning = screen.getByTestId('incomplete-costing')
      expect(warning).toBeInTheDocument()
      expect(warning).toHaveTextContent('Incompletely costed')
    })

    it('lists every reason, in the words the engine used', () => {
      render(<CostBreakdownPanel breakdown={incomplete} />)

      const warning = screen.getByTestId('incomplete-costing')
      expect(warning).toHaveTextContent(
        'this printer has no cost policy, so no machine rate could be derived',
      )
      expect(warning).toHaveTextContent('the item has no print time, so machine occupancy is unknown')
    })

    it('does not invent a machine line to fill the gap', () => {
      render(<CostBreakdownPanel breakdown={incomplete} />)
      expect(screen.queryByTestId('cost-line-machine')).not.toBeInTheDocument()
    })

    it('carries the warning as an alert, so it is announced', () => {
      render(<CostBreakdownPanel breakdown={incomplete} />)
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
  })

  it('shows no warning when nothing is missing', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)
    expect(screen.queryByTestId('incomplete-costing')).not.toBeInTheDocument()
  })

  it('says a perfect yield adds nothing rather than leaving a bare zero', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({ yield_applied: '1', failure_premium: '0' })}
      />,
    )
    expect(screen.getByText(/costed at a perfect yield/)).toBeInTheDocument()
  })

  it('says so when an item has no costed line at all', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [],
          at_risk_subtotal: '0',
          not_at_risk_subtotal: '0',
          failure_premium: '0',
          total_make_cost: '0',
        })}
      />,
    )
    expect(screen.getByTestId('no-cost-lines')).toBeInTheDocument()
  })

  it('honours the currency symbol it is given', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} currencySymbol="CA$" />)
    expect(screen.getByTestId('total-make-cost')).toHaveTextContent('CA$20.30')
  })
})

describe('a line whose figure is under review (task T153)', () => {
  // FR-042e. `ProvenanceBadge` has accepted `hasPendingRevision` since T055a
  // and the panel never passed it, because `CostLine` carried only `source`
  // and `as_of`. The flag was served on the provenance resource alone — so an
  // operator reading a cost breakdown saw a figure that telemetry already
  // disputed, with nothing on the screen to say a proposal was waiting. These
  // are the tests for the line carrying it.

  it('marks the line a proposal is held against', () => {
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [line({ key: 'machine', label: 'Machine occupancy', has_pending_revision: true })],
        })}
      />,
    )

    const row = screen.getByTestId('cost-line-machine')
    expect(within(row).getByTestId('provenance-pending-revision')).toBeInTheDocument()
  })

  it('leaves the other lines unmarked', () => {
    // The control. A flag on every line is the same as a flag on none.
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [
            line({ key: 'machine', label: 'Machine occupancy', has_pending_revision: true }),
            line({ key: 'material', label: 'Filament in the part' }),
          ],
        })}
      />,
    )

    expect(
      within(screen.getByTestId('cost-line-material')).queryByTestId(
        'provenance-pending-revision',
      ),
    ).not.toBeInTheDocument()
  })

  it('still shows the amount in force beside the mark', () => {
    // Constitution VII: telemetry proposes and does not reprice. The figure on
    // the line is the one pricing is using, and hiding it because an
    // observation disagrees would be the sensor repricing by omission.
    render(
      <CostBreakdownPanel
        breakdown={breakdown({
          lines: [line({ key: 'machine', amount: '2.21', has_pending_revision: true })],
        })}
        currencySymbol="CA$"
      />,
    )

    expect(screen.getByTestId('cost-line-machine')).toHaveTextContent('CA$2.21')
  })

  it('marks nothing when no proposal is waiting', () => {
    render(<CostBreakdownPanel breakdown={breakdown()} />)

    expect(screen.queryByTestId('provenance-pending-revision')).not.toBeInTheDocument()
  })

  it('treats a line from an older response with no flag as unmarked', () => {
    // A cached response predating the field. Absent is "nobody has proposed
    // anything", not "under review".
    const legacy = { ...line() } as Record<string, unknown>
    delete legacy.has_pending_revision

    render(
      <CostBreakdownPanel
        breakdown={breakdown({ lines: [legacy as unknown as CostLine] })}
      />,
    )

    expect(screen.queryByTestId('provenance-pending-revision')).not.toBeInTheDocument()
  })
})
