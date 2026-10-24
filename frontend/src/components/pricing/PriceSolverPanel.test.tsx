/**
 * PriceSolverPanel and PriceLadder tests (task T089a).
 *
 * Two properties carry the whole of User Story 4 on the frontend, and both are
 * about what the interface must *not* do:
 *
 * 1. **The solved price is a proposal that publishes nothing** (US4 scenario
 *    5). The panel renders an answer and an apply control; it performs no
 *    write, and the price only leaves it when the operator presses apply.
 * 2. **An unachievable target renders its binding constraint, not a number**
 *    (FR-035). A plausible-looking price for an impossible target is the one
 *    output that would actually cost the operator money, so the panel is
 *    tested for the absence of a figure as well as the presence of the reason.
 *
 * The ladder's half of that restraint is FR-007: no rung is recommended, and
 * there is no affordance through which one could be.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PriceLadder } from './PriceLadder'
import { PriceSolverPanel } from './PriceSolverPanel'
import type {
  PriceLadder as PriceLadderData,
  PriceLadderRung,
  PriceSolveResult,
} from '@/types/pricing'

/** The golden case's answer: CA$64.64 for a 35% target. */
function solved(overrides: Partial<PriceSolveResult> = {}): PriceSolveResult {
  return {
    product_id: 'p1',
    sales_channel_id: 'c1',
    as_of: '2026-06-01',
    achievable: true,
    reason: null,
    binding_constraint: null,
    target_margin_pct: '35',
    margin_basis: 'customer_total',
    margin_basis_label: 'of the total the customer paid',
    required_price_raw: '64.6400',
    required_price_rounded: '64.64',
    adjustments: [],
    binding_clamps: [],
    margin_pct_at_price: '35.0000',
    profit_at_price: '22.62',
    make_cost: '20.30',
    postage_paid: '9.50',
    fees: [],
    inputs: {
      make_cost: '20.30',
      postage_paid: '9.50',
      target_margin_pct: '35',
      margin_basis: 'customer_total',
    },
    passes: 1,
    is_proposal: true,
    ...overrides,
  }
}

function unachievable(overrides: Partial<PriceSolveResult> = {}): PriceSolveResult {
  return solved({
    achievable: false,
    reason: 'unachievable',
    binding_constraint:
      'a target of 90.00% of the total the customer paid plus 12.50% of percentage fees ' +
      'and 2.50% of reserves reaches or exceeds the whole amount',
    target_margin_pct: '90',
    required_price_raw: null,
    required_price_rounded: null,
    margin_pct_at_price: null,
    profit_at_price: null,
    adjustments: [],
    ...overrides,
  })
}

function rung(overrides: Partial<PriceLadderRung> = {}): PriceLadderRung {
  return {
    price: '60.00',
    margin_pct: '31.1333',
    profit: '18.68',
    margin_basis: 'customer_total',
    profit_per_machine_hour: '1.97',
    ...overrides,
  }
}

function ladderData(overrides: Partial<PriceLadderData> = {}): PriceLadderData {
  return {
    product_id: 'p1',
    sales_channel_id: 'c1',
    as_of: '2026-06-01',
    price_from: '55.00',
    price_to: '65.00',
    step: '5.00',
    margin_basis: 'customer_total',
    margin_basis_label: 'of the total the customer paid',
    make_cost: '20.30',
    postage_paid: '9.50',
    machine_hours: '9.5',
    rungs: [
      rung({ price: '55.00', margin_pct: '26.2364', profit: '14.43', profit_per_machine_hour: '1.52' }),
      rung(),
      rung({ price: '65.00', margin_pct: '35.2769', profit: '22.93', profit_per_machine_hour: '2.41' }),
    ],
    ...overrides,
  }
}

// ===========================================================================
// The proposal publishes nothing
// ===========================================================================

describe('PriceSolverPanel', () => {
  describe('the answer is a proposal and nothing is published', () => {
    it('labels the price as a proposal', () => {
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} />)

      expect(screen.getByTestId('proposal-badge')).toBeInTheDocument()
    })

    it('says in words that nothing reached the channel', () => {
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} />)

      expect(screen.getByTestId('nothing-published')).toHaveTextContent(
        /nothing has been published/i,
      )
    })

    it('does not apply the price by rendering it', () => {
      const onApply = vi.fn()
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} onApply={onApply} />)

      expect(onApply).not.toHaveBeenCalled()
    })

    it('hands the price to the host only when the operator applies it', async () => {
      const onApply = vi.fn()
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} onApply={onApply} />)

      await userEvent.click(screen.getByTestId('apply-price-button'))

      expect(onApply).toHaveBeenCalledExactlyOnceWith('64.64')
    })

    it('renders no apply control when the host provides no way to write', () => {
      // A viewer's state: costs and margins are visible to every role, and
      // only editing is restricted (FR-007c).
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} />)

      expect(screen.queryByTestId('apply-price-button')).not.toBeInTheDocument()
    })

    it('lets the operator reject the proposal', async () => {
      const onDismiss = vi.fn()
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} onDismiss={onDismiss} />)

      await userEvent.click(screen.getByTestId('reject-price-button'))

      expect(onDismiss).toHaveBeenCalledOnce()
    })

    it('solves only when asked', async () => {
      const onSolve = vi.fn()
      render(<PriceSolverPanel onSolve={onSolve} />)

      expect(onSolve).not.toHaveBeenCalled()
      await userEvent.click(screen.getByTestId('solve-button'))
      expect(onSolve).toHaveBeenCalledOnce()
    })

    it('passes the target the operator typed, as a string', async () => {
      const onSolve = vi.fn()
      render(<PriceSolverPanel onSolve={onSolve} />)

      const input = screen.getByTestId('target-margin-input')
      await userEvent.clear(input)
      await userEvent.type(input, '42.5')
      await userEvent.click(screen.getByTestId('solve-button'))

      expect(onSolve).toHaveBeenCalledWith(
        expect.objectContaining({ target_margin_pct: '42.5' }),
      )
    })

    it('refuses to solve a target that is not a percentage', async () => {
      const onSolve = vi.fn()
      render(<PriceSolverPanel onSolve={onSolve} />)

      const input = screen.getByTestId('target-margin-input')
      await userEvent.clear(input)
      await userEvent.type(input, '120')
      await userEvent.click(screen.getByTestId('solve-button'))

      expect(onSolve).not.toHaveBeenCalled()
      expect(screen.getByTestId('target-invalid')).toBeInTheDocument()
    })
  })

  // =========================================================================
  // FR-035
  // =========================================================================

  describe('an unachievable target', () => {
    it('renders the binding constraint', () => {
      render(<PriceSolverPanel result={unachievable()} onSolve={vi.fn()} />)

      expect(screen.getByTestId('binding-constraint')).toHaveTextContent(
        /reaches or exceeds the whole amount/i,
      )
    })

    it('names the target that could not be met', () => {
      render(<PriceSolverPanel result={unachievable()} onSolve={vi.fn()} />)

      expect(screen.getByTestId('unachievable-target')).toHaveTextContent(/90%/)
    })

    it('shows no price at all', () => {
      render(<PriceSolverPanel result={unachievable()} onSolve={vi.fn()} />)

      expect(screen.queryByTestId('solve-result')).not.toBeInTheDocument()
      expect(screen.queryByTestId('proposed-price')).not.toBeInTheDocument()
    })

    it('offers nothing to apply', () => {
      // The failure this guards: an apply button beside an impossible target.
      render(
        <PriceSolverPanel result={unachievable()} onSolve={vi.fn()} onApply={vi.fn()} />,
      )

      expect(screen.queryByTestId('apply-price-button')).not.toBeInTheDocument()
    })

    it('is not rendered as an error, because the request was valid', () => {
      render(<PriceSolverPanel result={unachievable()} onSolve={vi.fn()} />)

      expect(screen.queryByTestId('solver-error')).not.toBeInTheDocument()
    })
  })

  // =========================================================================
  // FR-033 and FR-034
  // =========================================================================

  describe('every move away from the solved price is shown', () => {
    it('shows the raw price beside the adjusted one', () => {
      render(
        <PriceSolverPanel
          result={solved({
            required_price_raw: '64.6400',
            required_price_rounded: '64.99',
            adjustments: [
              {
                key: 'rounding',
                label: 'Rounded by the psychological 99 rule',
                from_price: '64.64',
                to_price: '64.99',
                delta: '0.35',
              },
            ],
          })}
          onSolve={vi.fn()}
        />,
      )

      expect(screen.getByTestId('proposed-price')).toHaveTextContent('$64.99')
      expect(screen.getByTestId('adjustment-raw')).toHaveTextContent('$64.64')
    })

    it('names each adjustment', () => {
      render(
        <PriceSolverPanel
          result={solved({
            required_price_rounded: '75.00',
            adjustments: [
              {
                key: 'rounding',
                label: 'Rounded by the nearest dollar rule',
                from_price: '64.64',
                to_price: '65.00',
                delta: '0.36',
              },
              {
                key: 'free_shipping_snap',
                label: 'Snapped up to the free-shipping threshold of 75.00',
                from_price: '65.00',
                to_price: '75.00',
                delta: '10.00',
              },
            ],
          })}
          onSolve={vi.fn()}
        />,
      )

      expect(screen.getByTestId('adjustment-rounding')).toHaveTextContent(/nearest dollar/i)
      expect(screen.getByTestId('adjustment-free_shipping_snap')).toHaveTextContent(
        /free-shipping threshold/i,
      )
    })

    it('says so when nothing moved the price', () => {
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} />)

      expect(screen.getByTestId('no-adjustments')).toBeInTheDocument()
    })

    it('reports a capped fee as binding rather than as a miscalculation', () => {
      render(
        <PriceSolverPanel
          result={solved({ binding_clamps: ['transaction'] })}
          onSolve={vi.fn()}
        />,
      )

      expect(screen.getByTestId('binding-clamps')).toHaveTextContent(/transaction/)
      expect(screen.getByTestId('binding-clamps')).toHaveTextContent(/binding at this price/i)
    })

    it('lists every input behind the answer', () => {
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} />)

      const inputs = screen.getByTestId('solve-inputs')
      expect(within(inputs).getByText('make cost')).toBeInTheDocument()
      expect(within(inputs).getByText('20.30')).toBeInTheDocument()
    })

    it('names the basis beside the margin it achieved', () => {
      render(<PriceSolverPanel result={solved()} onSolve={vi.fn()} />)

      expect(screen.getByTestId('achieved-margin')).toHaveTextContent('35.0%')
      expect(screen.getByTestId('margin-basis-label')).toBeInTheDocument()
    })

    it('renders money from the decimal string, never a parsed float', () => {
      render(
        <PriceSolverPanel
          result={solved({ required_price_rounded: '1064.30', profit_at_price: '0.10' })}
          onSolve={vi.fn()}
        />,
      )

      expect(screen.getByTestId('proposed-price')).toHaveTextContent('$1064.30')
    })
  })

  describe('while solving and when it fails', () => {
    it('shows that it is working', () => {
      render(<PriceSolverPanel isSolving onSolve={vi.fn()} />)

      expect(screen.getByTestId('solve-button')).toBeDisabled()
    })

    it('shows a real failure as an error, distinct from an unachievable target', () => {
      render(<PriceSolverPanel error={new Error('Product not found')} onSolve={vi.fn()} />)

      expect(screen.getByTestId('solver-error')).toHaveTextContent('Product not found')
      expect(screen.queryByTestId('unachievable-target')).not.toBeInTheDocument()
    })

    it('shows no result before the first solve', () => {
      render(<PriceSolverPanel onSolve={vi.fn()} />)

      expect(screen.queryByTestId('solve-result')).not.toBeInTheDocument()
      expect(screen.queryByTestId('unachievable-target')).not.toBeInTheDocument()
    })
  })
})

// ===========================================================================
// FR-007: the ladder recommends nothing
// ===========================================================================

describe('PriceLadder', () => {
  const RECOMMENDATION_WORDS = /recommend|suggested|best|optimal|ideal|should charge/i

  it('shows a row for each price in the range', () => {
    render(<PriceLadder ladder={ladderData()} />)

    expect(screen.getByTestId('ladder-rung-55.00')).toBeInTheDocument()
    expect(screen.getByTestId('ladder-rung-60.00')).toBeInTheDocument()
    expect(screen.getByTestId('ladder-rung-65.00')).toBeInTheDocument()
  })

  it('keeps the rows in price order, so nothing is ranked', () => {
    render(<PriceLadder ladder={ladderData()} />)

    const rows = screen.getAllByTestId(/^ladder-rung-/)
    const prices = rows.map((row) => row.getAttribute('data-testid'))
    expect(prices).toEqual([
      'ladder-rung-55.00',
      'ladder-rung-60.00',
      'ladder-rung-65.00',
    ])
  })

  it('recommends no price, in words or in markup', () => {
    render(<PriceLadder ladder={ladderData()} onChoose={vi.fn()} />)

    expect(screen.getByTestId('price-ladder').textContent).not.toMatch(RECOMMENDATION_WORDS)
  })

  it('says why it offers no recommendation', () => {
    render(<PriceLadder ladder={ladderData()} />)

    expect(screen.getByTestId('price-ladder')).toHaveTextContent(
      /not something this system can work out/i,
    )
  })

  it('writes nothing back when a price is chosen', async () => {
    const onChoose = vi.fn()
    render(<PriceLadder ladder={ladderData()} onChoose={onChoose} />)

    await userEvent.click(screen.getByTestId('choose-65.00'))

    expect(onChoose).toHaveBeenCalledExactlyOnceWith('65.00')
  })

  it('says that nothing on the table was saved', () => {
    render(<PriceLadder ladder={ladderData()} />)

    expect(screen.getByTestId('ladder-footnote')).toHaveTextContent(/nothing on this table/i)
  })

  it('is read-only when the host offers no way to choose', () => {
    render(<PriceLadder ladder={ladderData()} />)

    expect(screen.queryByTestId('choose-65.00')).not.toBeInTheDocument()
  })

  it('names the basis every percentage is taken on', () => {
    render(<PriceLadder ladder={ladderData()} />)

    expect(screen.getByTestId('margin-basis-label')).toBeInTheDocument()
  })

  it('reports profit per machine-hour when the print is timed', () => {
    render(<PriceLadder ladder={ladderData()} />)

    expect(screen.getByTestId('ladder-rung-65.00')).toHaveTextContent('$2.41')
  })

  it('omits the per-hour column entirely when nobody timed the print', () => {
    render(
      <PriceLadder
        ladder={ladderData({
          machine_hours: null,
          rungs: [rung({ profit_per_machine_hour: null })],
        })}
      />,
    )

    expect(screen.queryByText(/profit per machine-hour/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('ladder-footnote')).toHaveTextContent(/nobody has timed/i)
  })

  it('marks the price currently in effect as a fact, not a recommendation', () => {
    render(<PriceLadder ladder={ladderData()} currentPrice="60.00" />)

    expect(screen.getByTestId('ladder-rung-60.00')).toHaveAttribute('data-current', 'true')
    expect(screen.getByTestId('current-price-marker')).toHaveTextContent('current')
    expect(screen.getByTestId('ladder-rung-65.00')).not.toHaveAttribute('data-current')
  })

  it('reads an undefined margin as undefined, never as zero', () => {
    render(
      <PriceLadder
        ladder={ladderData({
          rungs: [rung({ margin_pct: null, profit: '-5.00' })],
        })}
      />,
    )

    const row = screen.getByTestId('ladder-rung-60.00')
    expect(row).toHaveTextContent(/undefined/i)
    expect(row).not.toHaveTextContent('0.0%')
  })

  it('shows an empty range as empty rather than as a verdict', () => {
    render(<PriceLadder ladder={ladderData({ rungs: [] })} />)

    expect(screen.getByTestId('ladder-empty')).toBeInTheDocument()
  })

  it('shows a failure without inventing figures', () => {
    render(<PriceLadder error={new Error('Product not found')} />)

    expect(screen.getByTestId('ladder-error')).toHaveTextContent('Product not found')
    expect(screen.queryByTestId('ladder-table')).not.toBeInTheDocument()
  })
})

describe('a date no fee rule covers (T236)', () => {
  const lapsed = 'no fee rule on this channel covers 2026-10-24'

  it('is reported on the solver rather than priced at zero fees', () => {
    render(
      <PriceSolverPanel result={solved({ incomplete_reasons: [lapsed] })} onSolve={vi.fn()} />,
    )
    expect(screen.getByTestId('solver-incomplete')).toHaveTextContent(lapsed)
  })

  it('is reported on the ladder', () => {
    render(<PriceLadder ladder={ladderData({ incomplete_reasons: [lapsed] })} />)
    expect(screen.getByTestId('ladder-incomplete')).toHaveTextContent(lapsed)
  })

  it('says nothing when every date is covered', () => {
    render(<PriceSolverPanel result={solved({ incomplete_reasons: [] })} onSolve={vi.fn()} />)
    expect(screen.queryByTestId('solver-incomplete')).not.toBeInTheDocument()
  })
})
