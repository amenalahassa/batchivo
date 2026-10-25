/**
 * The served margin reaches a screen (T244, US3/AC1, US3/AC3, US3/AC4).
 *
 * Each fee is named with its clamp and incidence, postage paid is set against
 * shipping charged as its own line -- negative when the shipping loses money --
 * the reserves are listed, and the basis travels with the percentage.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ProductMarginBreakdown } from './ProductMarginBreakdown'
import { feeRulesApi } from '@/lib/api/feeRules'
import type { FeeCharge, ProductMargin } from '@/types/pricing'

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: { getMargin: vi.fn() },
}))

const api = vi.mocked(feeRulesApi)

function fee(overrides: Partial<FeeCharge> = {}): FeeCharge {
  return {
    name: 'transaction',
    basis: 'item_subtotal',
    amount: '4.22',
    clamp_applied: null,
    is_expected: false,
    rate_pct: '6.5',
    fixed_amount: '0',
    basis_amount: '64.99',
    incidence_pct: null,
    ...overrides,
  }
}

function margin(overrides: Partial<ProductMargin> = {}): ProductMargin {
  return {
    product_id: 'product-1',
    sales_channel_id: 'channel-1',
    as_of: '2026-10-24',
    list_price: '64.99',
    shipping_revenue: '0.00',
    postage_paid: '4.10',
    shipping_net: '-4.10',
    make_cost: '18.37',
    fees: [
      fee(),
      fee({ name: 'payment cap', amount: '5.00', clamp_applied: 'max' }),
      fee({ name: 'offsite ads', amount: '1.95', is_expected: true, incidence_pct: '15' }),
    ],
    fee_total: '11.17',
    deductions: [
      {
        key: 'refund_reserve',
        label: 'Refund reserve',
        amount: '1.30',
        rate_pct: '2',
        basis_amount: '64.99',
      },
    ],
    deduction_total: '1.30',
    net_revenue: '48.42',
    profit: '30.05',
    margin_pct: '46.2',
    margin_basis: 'customer_total',
    margin_basis_label: 'of the customer total',
    margin_basis_amount: '64.99',
    sales_tax_collected: '0.00',
    sales_tax_liability: '0.00',
    tax_remitter: 'marketplace',
    tax_exclusive_derived: false,
    revenue_tax_exclusive: '64.99',
    observed_share: '0.4000',
    assumed_share: '0.6000',
    incomplete_reasons: [],
    ...overrides,
  }
}

function renderPanel(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('ProductMarginBreakdown', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getMargin.mockResolvedValue(margin())
  })

  it('names each fee, flags a bound cap and an expected fee', async () => {
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    expect(await screen.findByText('transaction')).toBeInTheDocument()
    expect(screen.getByTestId('fee-clamp-payment cap')).toHaveTextContent('Cap applied')
    expect(screen.getByTestId('fee-expected-offsite ads')).toHaveTextContent('Expected')
  })

  it('asks for a tier row margin at that tier quantity (T258)', async () => {
    renderPanel(
      <ProductMarginBreakdown productId="product-1" channelId="channel-1" quantity={3} />,
    )

    expect(await screen.findByText('transaction')).toBeInTheDocument()
    expect(api.getMargin).toHaveBeenCalledWith('product-1', 'channel-1', { quantity: 3 })
  })

  it('labels the figures in the currency the margin was computed in (T261)', async () => {
    api.getMargin.mockResolvedValue(margin({ currency: 'USD', profit: '30.05' }))
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    expect(await screen.findByTestId('margin-profit')).toHaveTextContent('$30.05')
    expect(screen.getByTestId('margin-profit')).not.toHaveTextContent('£30.05')
  })

  it('sets postage paid against shipping charged as its own, negative, line', async () => {
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    const line = within(await screen.findByTestId('margin-shipping-net'))
    expect(line.getByText('Shipping margin')).toBeInTheDocument()
    expect(line.getByText(/-£4\.10|£-4\.10/)).toHaveClass('text-red-600')
  })

  it('lists the reserves and the basis beside the percentage', async () => {
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    expect(await screen.findByTestId('margin-deduction-refund_reserve')).toHaveTextContent(
      'Refund reserve',
    )
    expect(screen.getByTestId('margin-percentage')).toHaveTextContent('46.2%')
    expect(screen.getByText('of the customer total')).toBeInTheDocument()
    expect(screen.getByTestId('margin-profit')).toHaveTextContent('£30.05')
  })

  it('says how much of the make-cost is evidence', async () => {
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    expect(await screen.findByTestId('margin-observed-share')).toHaveTextContent('40%')
  })

  it('names what is missing rather than hiding it', async () => {
    api.getMargin.mockResolvedValue(
      margin({ incomplete_reasons: ['the fee rule "listing" lapsed on 2026-09-30'] }),
    )
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    expect(await screen.findByTestId('margin-incomplete')).toHaveTextContent('lapsed')
  })

  it('shows a product not priced on the channel as unpriced, not as zero', async () => {
    api.getMargin.mockRejectedValue(new Error('This product is not priced on this channel'))
    renderPanel(<ProductMarginBreakdown productId="product-1" channelId="channel-1" />)

    expect(await screen.findByText('No margin to show')).toBeInTheDocument()
    expect(screen.queryByText('£0.00')).not.toBeInTheDocument()
  })
})
