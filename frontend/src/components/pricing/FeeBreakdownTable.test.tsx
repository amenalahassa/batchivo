/**
 * FeeBreakdownTable and MarginBasisLabel tests (task T085a).
 *
 * The three things these components exist to make visible, each tested as a
 * reader would need it rather than as markup:
 *
 * 1. **A clamp that bound is said to have bound** (FR-021c). A capped fee
 *    charging less than its rate implies otherwise reads as a bug in the
 *    engine, which is how an operator stops trusting a figure that was right.
 * 2. **An expectation is labelled as one** (FR-029). What a channel charges on
 *    average is not what it charged here, and presenting the two identically
 *    turns a planning figure into a receipt.
 * 3. **Every percentage names its basis** (FR-031b). The same sale is 35.3% of
 *    the customer total and 42.2% of net revenue after fees; a bare number is
 *    one two people will disagree about while reading the same screen.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { FeeBreakdownTable } from './FeeBreakdownTable'
import { MarginBasisLabel, MarginFigure } from './MarginBasisLabel'
import type { FeeBasis, FeeCharge, MarginBasis } from '@/types/pricing'

function charge(overrides: Partial<FeeCharge> = {}): FeeCharge {
  return {
    name: 'transaction',
    basis: 'item_plus_shipping',
    amount: '4.22',
    clamp_applied: null,
    is_expected: false,
    rate_pct: '6.5000',
    fixed_amount: '0.00',
    basis_amount: '64.99',
    incidence_pct: null,
    ...overrides,
  }
}

/** The golden case's stack: 12.5% plus CA$2.52, totalling CA$10.64. */
function goldenStack(): FeeCharge[] {
  return [
    charge(),
    charge({
      name: 'payment_processing',
      basis: 'order_total',
      amount: '2.25',
      rate_pct: '3.0000',
      fixed_amount: '0.30',
    }),
    charge({
      name: 'regulatory_operating',
      basis: 'item_subtotal',
      amount: '2.17',
      rate_pct: '3.0000',
      fixed_amount: '0.22',
    }),
    charge({
      name: 'order_handling',
      basis: 'per_order',
      amount: '2.00',
      rate_pct: '0',
      fixed_amount: '2.00',
      basis_amount: '1',
    }),
  ]
}

describe('FeeBreakdownTable', () => {
  describe('every fee names what it was charged on', () => {
    it('shows the basis for each fee', () => {
      render(<FeeBreakdownTable charges={goldenStack()} currencySymbol="$" />)

      expect(
        within(screen.getByTestId('fee-basis-transaction')).getByText('Item + shipping'),
      ).toBeInTheDocument()
      expect(
        within(screen.getByTestId('fee-basis-payment_processing')).getByText('Order total'),
      ).toBeInTheDocument()
      expect(
        within(screen.getByTestId('fee-basis-regulatory_operating')).getByText('Item price'),
      ).toBeInTheDocument()
      expect(
        within(screen.getByTestId('fee-basis-order_handling')).getByText('Per order'),
      ).toBeInTheDocument()
    })

    it('shows the amount the rate was applied to, so the fee is recomputable', () => {
      render(<FeeBreakdownTable charges={[charge()]} currencySymbol="$" />)

      expect(screen.getByTestId('fee-basis-transaction')).toHaveTextContent('$64.99')
    })

    it('renders a count basis as a multiplier rather than as money', () => {
      render(
        <FeeBreakdownTable
          charges={[
            charge({
              name: 'per_unit',
              basis: 'per_unit_sold',
              amount: '1.35',
              rate_pct: '0',
              fixed_amount: '0.45',
              basis_amount: '3',
            }),
          ]}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('fee-basis-per_unit')).toHaveTextContent('× 3')
      expect(screen.getByTestId('fee-basis-per_unit')).not.toHaveTextContent('$3')
    })

    it('does not show a rate on a count basis, where a rate has no meaning', () => {
      render(
        <FeeBreakdownTable
          charges={[charge({ name: 'per_order', basis: 'per_order', rate_pct: '0' })]}
          currencySymbol="$"
        />,
      )

      const row = screen.getByTestId('fee-row-per_order')
      expect(within(row).queryByText(/%/)).not.toBeInTheDocument()
    })

    it('renders each amount from the decimal string it was sent', () => {
      render(<FeeBreakdownTable charges={goldenStack()} currencySymbol="$" />)

      expect(screen.getByTestId('fee-amount-transaction')).toHaveTextContent('$4.22')
      expect(screen.getByTestId('fee-amount-order_handling')).toHaveTextContent('$2.00')
    })

    it('shows the total the API computed rather than summing the rows itself', () => {
      // The rows sum to 10.64 here, but the total is whatever the API sent: the
      // engine rounds the stack once, and a table that re-added the rounded
      // rows could disagree with the margin by a cent.
      render(<FeeBreakdownTable charges={goldenStack()} total="10.64" currencySymbol="$" />)

      expect(screen.getByTestId('fee-total')).toHaveTextContent('$10.64')
    })
  })

  describe('a clamp that bound says so (FR-021c)', () => {
    it('flags a fee whose cap bound', () => {
      render(
        <FeeBreakdownTable
          charges={[charge({ amount: '5.00', clamp_applied: 'max' })]}
          currencySymbol="$"
        />,
      )

      const flag = screen.getByTestId('fee-clamp-transaction')
      expect(flag).toHaveTextContent('Cap applied')
      expect(flag).toHaveAttribute('data-clamp', 'max')
    })

    it('explains that a capped fee has stopped rising with the price', () => {
      render(
        <FeeBreakdownTable
          charges={[charge({ amount: '5.00', clamp_applied: 'max' })]}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('fee-clamp-note-transaction')).toHaveTextContent(
        /stops rising with the price/,
      )
    })

    it('flags a fee whose minimum bound, distinctly from a cap', () => {
      render(
        <FeeBreakdownTable
          charges={[charge({ amount: '20.00', clamp_applied: 'min' })]}
          currencySymbol="$"
        />,
      )

      const flag = screen.getByTestId('fee-clamp-transaction')
      expect(flag).toHaveTextContent('Minimum applied')
      expect(flag).toHaveAttribute('data-clamp', 'min')
      expect(screen.getByTestId('fee-clamp-note-transaction')).toHaveTextContent(
        /stops falling with the price/,
      )
    })

    it('flags nothing when no clamp bound', () => {
      render(<FeeBreakdownTable charges={[charge()]} currencySymbol="$" />)

      expect(screen.queryByTestId('fee-clamp-transaction')).not.toBeInTheDocument()
      expect(screen.queryByTestId('fee-clamp-note-transaction')).not.toBeInTheDocument()
    })

    it('flags only the fee that was clamped, not its neighbours', () => {
      render(
        <FeeBreakdownTable
          charges={[charge({ amount: '5.00', clamp_applied: 'max' }), charge({ name: 'other' })]}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('fee-clamp-transaction')).toBeInTheDocument()
      expect(screen.queryByTestId('fee-clamp-other')).not.toBeInTheDocument()
    })
  })

  describe('an expectation is labelled as one (FR-029)', () => {
    it('flags a fee applied at an expected incidence', () => {
      render(
        <FeeBreakdownTable
          charges={[
            charge({
              name: 'offsite_ads',
              amount: '1.95',
              rate_pct: '15.0000',
              incidence_pct: '20.0000',
              is_expected: true,
            }),
          ]}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('fee-expected-offsite_ads')).toHaveTextContent('Expected')
    })

    it('says what share of orders the expectation covers', () => {
      render(
        <FeeBreakdownTable
          charges={[
            charge({
              name: 'offsite_ads',
              incidence_pct: '20.0000',
              is_expected: true,
            }),
          ]}
          currencySymbol="$"
        />,
      )

      const note = screen.getByTestId('fee-expected-note-offsite_ads')
      expect(note).toHaveTextContent('20%')
      expect(note).toHaveTextContent(/not an amount charged here/)
    })

    it('does not flag a fee charged on every order', () => {
      render(<FeeBreakdownTable charges={[charge()]} currencySymbol="$" />)

      expect(screen.queryByTestId('fee-expected-transaction')).not.toBeInTheDocument()
    })

    it('flags both a clamp and an expectation on the same fee', () => {
      render(
        <FeeBreakdownTable
          charges={[
            charge({
              name: 'capped_ads',
              amount: '2.50',
              clamp_applied: 'max',
              incidence_pct: '50.0000',
              is_expected: true,
            }),
          ]}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('fee-clamp-capped_ads')).toBeInTheDocument()
      expect(screen.getByTestId('fee-expected-capped_ads')).toBeInTheDocument()
    })
  })

  describe('periodic rules are shown, not dropped (FR-025)', () => {
    it('puts periodic fees in their own section', () => {
      render(
        <FeeBreakdownTable
          charges={goldenStack()}
          periodic={[
            charge({
              name: 'listing',
              basis: 'per_listing',
              amount: '2.20',
              rate_pct: '0',
              fixed_amount: '0.22',
              basis_amount: '10',
            }),
          ]}
          currencySymbol="$"
        />,
      )

      const section = screen.getByTestId('fee-periodic-section')
      expect(section).toHaveTextContent('Not charged on this sale')
      expect(within(section).getByTestId('fee-row-listing')).toBeInTheDocument()
    })

    it('says why a periodic fee is not charged against the unit', () => {
      render(
        <FeeBreakdownTable
          charges={[]}
          periodic={[charge({ name: 'listing', basis: 'per_listing' })]}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('fee-periodic-section')).toHaveTextContent(
        /absorbed over a period/,
      )
    })

    it('shows no periodic section when there are none', () => {
      render(<FeeBreakdownTable charges={goldenStack()} currencySymbol="$" />)

      expect(screen.queryByTestId('fee-periodic-section')).not.toBeInTheDocument()
    })
  })

  describe('a channel with no fee rules', () => {
    it('says the fees are unmodelled rather than showing an empty table', () => {
      render(<FeeBreakdownTable charges={[]} currencySymbol="$" />)

      const empty = screen.getByTestId('fee-table-empty')
      expect(empty).toHaveTextContent(/no fee rules configured/)
      expect(empty).toHaveTextContent(/not a discount/)
    })
  })
})

describe('MarginBasisLabel', () => {
  const bases: MarginBasis[] = ['customer_total', 'item_price', 'net_revenue']

  it.each(bases)('renders a label for the %s basis', (basis) => {
    render(<MarginBasisLabel basis={basis} />)

    const label = screen.getByTestId('margin-basis-label')
    expect(label).toHaveAttribute('data-basis', basis)
    expect(label.textContent?.trim()).not.toBe('')
  })

  it('prefers the sentence the API sent over its own wording', () => {
    render(
      <MarginBasisLabel
        basis="customer_total"
        label="of the total the customer paid"
      />,
    )

    expect(screen.getByTestId('margin-basis-label')).toHaveTextContent(
      'of the total the customer paid',
    )
  })

  it('falls back to its own wording when the API sent none', () => {
    render(<MarginBasisLabel basis="net_revenue" label={null} />)

    expect(screen.getByTestId('margin-basis-label')).toHaveTextContent('of net revenue')
  })
})

describe('MarginFigure', () => {
  it('names the basis beside the percentage (FR-031b)', () => {
    render(
      <MarginFigure
        marginPct="35.2693"
        basis="customer_total"
        label="of the total the customer paid"
      />,
    )

    expect(screen.getByTestId('margin-percentage')).toHaveTextContent('35.3%')
    expect(screen.getByTestId('margin-basis-label')).toHaveTextContent(
      'of the total the customer paid',
    )
  })

  it('rounds to one place from the four the API sends', () => {
    render(<MarginFigure marginPct="42.1803" basis="net_revenue" />)

    expect(screen.getByTestId('margin-percentage')).toHaveTextContent('42.2%')
  })

  it('reports an undefined margin as undefined, never as zero', () => {
    // Net revenue after fees, with fees consuming the whole amount. A zero
    // here would read as break-even on a sale that lost money.
    render(<MarginFigure marginPct={null} basis="net_revenue" />)

    expect(screen.getByTestId('margin-percentage')).toHaveTextContent('Undefined')
    expect(screen.getByTestId('margin-percentage')).not.toHaveTextContent('0')
    expect(screen.getByTestId('margin-figure')).toHaveTextContent(
      /fees consume the whole basis/,
    )
  })

  it('still names the basis when the percentage is undefined', () => {
    render(<MarginFigure marginPct={null} basis="net_revenue" />)

    expect(screen.getByTestId('margin-basis-label')).toHaveAttribute(
      'data-basis',
      'net_revenue',
    )
  })

  it('cannot render a percentage without a basis', () => {
    // A type-level guarantee rather than a runtime one: `basis` is required on
    // MarginFigure, so there is no way to put a bare percentage on screen by
    // forgetting to pass one. This test records the intent so a future change
    // making it optional fails review rather than silently shipping.
    render(<MarginFigure marginPct="35.3" basis="item_price" />)

    expect(screen.getByTestId('margin-figure')).toContainElement(
      screen.getByTestId('margin-basis-label'),
    )
  })

  it('renders a negative margin as negative', () => {
    render(<MarginFigure marginPct="-12.5000" basis="customer_total" />)

    expect(screen.getByTestId('margin-percentage')).toHaveTextContent('-12.5%')
  })
})

describe('the basis labels cover every basis the API can send', () => {
  it('has a label for all seven fee bases', () => {
    const bases: FeeBasis[] = [
      'item_subtotal',
      'item_plus_shipping',
      'order_total',
      'per_listing',
      'per_order',
      'per_unit_sold',
      'per_month',
    ]

    render(
      <FeeBreakdownTable
        charges={bases.map((basis) => charge({ name: `fee-${basis}`, basis }))}
        currencySymbol="$"
      />,
    )

    for (const basis of bases) {
      const cell = screen.getByTestId(`fee-basis-fee-${basis}`)
      // A missing label would render the raw enum value, which is the failure
      // this asserts against.
      expect(cell.textContent).not.toContain(basis)
    }
  })
})
