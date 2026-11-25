/**
 * ChannelReconciliation tests.
 *
 * The two distinctions this screen exists to keep, and which a reader would be
 * misled by if either collapsed:
 *
 * * **"Nothing recorded" is not "agrees with plan."** A channel nobody has
 *   reconciled must show a dash, not a zero difference. A zero would claim a
 *   reconciliation that never happened.
 * * **"Unabsorbed" is not "free."** A period with no orders still owed its
 *   subscription. Dividing by zero would crash and reporting zero would lie,
 *   so the cost is reported as unabsorbed and the total is named.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { ChannelReconciliation } from './ChannelReconciliation'
import type { AbsorbedCost, CategoryReconciliation, ChannelPnL } from '@/types/pricing'

function reconciliationRow(
  overrides: Partial<CategoryReconciliation> = {},
): CategoryReconciliation {
  return {
    category: 'transaction',
    planned: '6.50',
    actual_period: '7.00',
    actual_order_scoped: '0.00',
    unallocated_remainder: '7.00',
    actual_total: '7.00',
    difference: '0.50',
    difference_pct_of_fee: '7.6923',
    ...overrides,
  }
}

function absorbed(overrides: Partial<AbsorbedCost> = {}): AbsorbedCost {
  return {
    key: 'monthly_cost',
    label: 'Channel subscription',
    total: '30.00',
    order_count: 3,
    per_order: '10.0000',
    is_unabsorbed: false,
    ...overrides,
  }
}

function pnl(overrides: Partial<ChannelPnL> = {}): ChannelPnL {
  return {
    channel_id: 'channel-1',
    period_start: '2026-06-01',
    period_end: '2026-06-30',
    order_count: 3,
    revenue_tax_exclusive: '150.00',
    sales_tax_collected: '0.00',
    sales_tax_liability: '0.00',
    postage_paid: '9.50',
    shipping_revenue: '5.00',
    shipping_net: '-4.50',
    planned_fee_total: '9.75',
    actual_fee_total: '10.25',
    unallocated_remainder: '0.00',
    fee_difference: '0.50',
    reconciliation: [reconciliationRow()],
    absorbed_costs: [absorbed()],
    unabsorbed_total: '0.00',
    make_cost_total: '0.00',
    profit: '100.75',
    margin_pct: '67.1667',
    margin_basis: 'customer_total',
    margin_basis_label: 'of the total the customer paid',
    ...overrides,
  }
}

describe('ChannelReconciliation', () => {
  describe('the headline figures', () => {
    it('shows revenue tax-exclusive', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.getByTestId('pnl-revenue')).toHaveTextContent('$150.00')
    })

    it('names the basis beside the margin (FR-031b)', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.getByTestId('margin-percentage')).toHaveTextContent('67.2%')
      expect(screen.getByTestId('margin-basis-label')).toHaveTextContent(
        'of the total the customer paid',
      )
    })

    it('keeps postage and shipping revenue as separate figures (FR-024)', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.getByTestId('pnl-shipping-revenue')).toHaveTextContent('$5.00')
      expect(screen.getByTestId('pnl-postage')).toHaveTextContent('$9.50')
      expect(screen.getByTestId('pnl-shipping-net')).toHaveTextContent('-$4.50')
    })

    it('says so when shipping cost more than it earned', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.getByTestId('pnl-shipping-net')).toHaveTextContent(
        /cost more than it earned/,
      )
    })

    it('shows a dash for recorded fees when nothing is reconciled', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({ actual_fee_total: null, fee_difference: null })}
          currencySymbol="$"
        />,
      )

      const cell = screen.getByTestId('pnl-actual-fees')
      expect(cell).toHaveTextContent('—')
      expect(cell).toHaveTextContent(/nothing reconciled yet/)
    })
  })

  describe('sales tax is a liability, never revenue (FR-028c, FR-028d)', () => {
    it('shows the liability apart from revenue when tax was collected', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({
            revenue_tax_exclusive: '100.00',
            sales_tax_collected: '13.00',
            sales_tax_liability: '13.00',
          })}
          currencySymbol="$"
        />,
      )

      const tax = screen.getByTestId('pnl-tax')
      expect(tax).toHaveTextContent('$13.00 collected')
      expect(tax).toHaveTextContent('$13.00 owed')
      expect(tax).toHaveTextContent(/never counted as revenue or profit/)
      expect(screen.getByTestId('pnl-revenue')).toHaveTextContent('$100.00')
    })

    it('omits the tax panel when none was collected', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.queryByTestId('pnl-tax')).not.toBeInTheDocument()
    })
  })

  describe('absorption over actual order volume (FR-025)', () => {
    it('shows the per-order share of a periodic cost', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.getByTestId('absorbed-per-order-monthly_cost')).toHaveTextContent(
        '$10.00',
      )
    })

    it('reports a cost as unabsorbed rather than free when there were no orders', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({
            order_count: 0,
            absorbed_costs: [
              absorbed({ order_count: 0, per_order: null, is_unabsorbed: true }),
            ],
            unabsorbed_total: '30.00',
          })}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('absorbed-unabsorbed-monthly_cost')).toHaveTextContent(
        'Unabsorbed',
      )
      expect(screen.getByTestId('absorbed-per-order-monthly_cost')).toHaveTextContent('—')
    })

    it('says a channel that sold nothing has not become free', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({
            order_count: 0,
            absorbed_costs: [
              absorbed({ order_count: 0, per_order: null, is_unabsorbed: true }),
            ],
            unabsorbed_total: '30.00',
          })}
          currencySymbol="$"
        />,
      )

      const warning = screen.getByTestId('pnl-no-orders')
      expect(warning).toHaveTextContent('$30.00')
      expect(warning).toHaveTextContent(/has not become free/)
    })

    it('shows no unabsorbed warning when there were orders', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.queryByTestId('pnl-no-orders')).not.toBeInTheDocument()
    })
  })

  describe('planned against recorded (FR-041d)', () => {
    it('shows the planned and recorded totals per category', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      const row = screen.getByTestId('reconcile-transaction')
      expect(row).toHaveTextContent('$6.50')
      expect(screen.getByTestId('reconcile-actual-transaction')).toHaveTextContent('$7.00')
      expect(screen.getByTestId('reconcile-difference-transaction')).toHaveTextContent(
        '$0.50',
      )
    })

    it('shows the difference as a share of the fee', () => {
      render(<ChannelReconciliation pnl={pnl()} currencySymbol="$" />)

      expect(screen.getByTestId('reconcile-difference-transaction')).toHaveTextContent(
        '7.7%',
      )
    })

    it('says a category is not reconciled rather than showing a zero difference', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({
            reconciliation: [
              reconciliationRow({
                actual_period: null,
                actual_total: null,
                unallocated_remainder: null,
                difference: null,
                difference_pct_of_fee: null,
              }),
            ],
          })}
          currencySymbol="$"
        />,
      )

      const difference = screen.getByTestId('reconcile-difference-transaction')
      expect(difference).toHaveTextContent('not reconciled')
      expect(difference).not.toHaveTextContent('$0.00')
    })

    it('flags a negative remainder as a contradiction to fix (FR-041c)', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({
            reconciliation: [
              reconciliationRow({
                actual_period: '5.00',
                actual_order_scoped: '9.00',
                unallocated_remainder: '-4.00',
                actual_total: '5.00',
              }),
            ],
          })}
          currencySymbol="$"
        />,
      )

      expect(screen.getByTestId('reconcile-overrun-transaction')).toHaveTextContent(
        /period figure needs correcting/,
      )
    })

    it('shows a category recorded but never planned', () => {
      render(
        <ChannelReconciliation
          pnl={pnl({
            reconciliation: [
              reconciliationRow({
                category: 'offsite_ads',
                planned: '0.00',
                actual_period: '9.75',
                actual_total: '9.75',
                unallocated_remainder: '9.75',
                difference: '9.75',
                difference_pct_of_fee: null,
              }),
            ],
          })}
          currencySymbol="$"
        />,
      )

      const row = screen.getByTestId('reconcile-offsite_ads')
      expect(within(row).getByText('offsite_ads')).toBeInTheDocument()
      expect(screen.getByTestId('reconcile-difference-offsite_ads')).toHaveTextContent(
        '$9.75',
      )
    })

    it('says so when nothing is planned and nothing recorded', () => {
      render(
        <ChannelReconciliation pnl={pnl({ reconciliation: [] })} currencySymbol="$" />,
      )

      expect(screen.getByTestId('reconciliation-empty')).toHaveTextContent(
        /No fees planned and none recorded/,
      )
    })
  })

  describe('an undefined margin', () => {
    it('reports it as undefined rather than as zero', () => {
      render(
        <ChannelReconciliation pnl={pnl({ margin_pct: null })} currencySymbol="$" />,
      )

      expect(screen.getByTestId('margin-percentage')).toHaveTextContent('Undefined')
    })
  })
})
