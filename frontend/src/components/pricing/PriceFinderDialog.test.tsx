/**
 * The solver and the ladder are reachable, and neither publishes (task T129).
 *
 * `PriceSolverPanel` and `PriceLadder` were built and tested in isolation and
 * imported by nothing, so SC-005 — "an operator obtains the price for a target
 * margin in a single request" — had no request to make. US4 scenario 5 adds
 * the constraint these tests hold onto: the result is a proposal the operator
 * applies, never something written to a channel on their behalf.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { PriceFinderDialog } from './PriceFinderDialog'
import { pricingApi } from '@/lib/api/pricing'
import type { PriceLadder, PriceSolveResult } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    trySolvePrice: vi.fn(),
    getPriceLadder: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)

function solved(overrides: Partial<PriceSolveResult> = {}): PriceSolveResult {
  return {
    product_id: 'product-1',
    sales_channel_id: 'channel-1',
    as_of: '2026-03-01',
    achievable: true,
    reason: null,
    binding_constraint: null,
    target_margin_pct: '35',
    margin_basis: 'customer_total',
    margin_basis_label: 'the total the customer paid',
    required_price_raw: '64.64',
    required_price_rounded: '64.99',
    adjustments: [],
    binding_clamps: [],
    margin_pct_at_price: '35.3',
    profit_at_price: '22.92',
    make_cost: '20.30',
    postage_paid: '0.00',
    fees: [],
    inputs: { make_cost: '20.30' },
    passes: 1,
    is_proposal: true,
    ...overrides,
  }
}

function ladder(overrides: Partial<PriceLadder> = {}): PriceLadder {
  return {
    product_id: 'product-1',
    sales_channel_id: 'channel-1',
    as_of: '2026-03-01',
    price_from: '45.49',
    price_to: '84.49',
    step: '3.90',
    margin_basis: 'customer_total',
    margin_basis_label: 'the total the customer paid',
    make_cost: '20.30',
    postage_paid: '0.00',
    machine_hours: '9.50',
    rungs: [
      {
        price: '59.99',
        margin_pct: '30.1',
        profit: '18.05',
        margin_basis: 'customer_total',
        profit_per_machine_hour: '1.90',
      },
      {
        price: '64.99',
        margin_pct: '35.3',
        profit: '22.92',
        margin_basis: 'customer_total',
        profit_per_machine_hour: '2.41',
      },
    ],
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('PriceFinderDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.trySolvePrice.mockResolvedValue(solved())
    mocked.getPriceLadder.mockResolvedValue(ladder())
  })

  it('offers both ways to reach a price', async () => {
    // One is a calculation (FR-032); the other is the operator's judgement
    // read off a ladder (FR-007). Offering only the first invites them to
    // treat a solved number as the answer.
    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={vi.fn()}
        productId="product-1"
        channelId="channel-1"
        currentPrice="64.99"
      />
    )

    expect(screen.getByRole('tab', { name: /from a target margin/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /across a range/i })).toBeInTheDocument()
  })

  it('says plainly that nothing is published', () => {
    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={vi.fn()}
        productId="product-1"
        channelId="channel-1"
      />
    )

    expect(screen.getByText(/nothing here is published to a channel/i)).toBeInTheDocument()
  })

  it('hands an applied price back instead of saving it', async () => {
    // US4 scenario 5. The caller turns it into a draft the operator saves.
    const onApply = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup({ delay: null })

    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={onOpenChange}
        productId="product-1"
        channelId="channel-1"
        currentPrice="64.99"
        onApply={onApply}
      />
    )

    await user.click(screen.getByRole('button', { name: /solve/i }))
    await waitFor(() => expect(mocked.trySolvePrice).toHaveBeenCalled())

    // Named by its amount, not just "Apply": the panel's rounding switch also
    // reads "Apply my rounding rule", and a test that matched both would pass
    // while the real control was missing.
    await user.click(await screen.findByRole('button', { name: /^Apply .*64\.99/ }))

    expect(onApply).toHaveBeenCalledWith('64.99')
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('offers no apply control without onApply, which is a viewer’s state', async () => {
    const user = userEvent.setup({ delay: null })

    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={vi.fn()}
        productId="product-1"
        channelId="channel-1"
        currentPrice="64.99"
      />
    )

    await user.click(screen.getByRole('button', { name: /solve/i }))
    await waitFor(() => expect(mocked.trySolvePrice).toHaveBeenCalled())

    expect(screen.queryByRole('button', { name: /^Apply .*64\.99/ })).not.toBeInTheDocument()
  })

  it('takes the ladder’s bounds and step as inputs, not constants', async () => {
    // T086a's rule, carried into the UI: the range is the operator's. It is
    // seeded from the price in effect so the midpoint is never a figure the
    // system invented.
    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={vi.fn()}
        productId="product-1"
        channelId="channel-1"
        currentPrice="64.99"
      />
    )

    const user = userEvent.setup({ delay: null })
    await user.click(screen.getByRole('tab', { name: /across a range/i }))

    expect(screen.getByLabelText('From')).toHaveValue('45.49')
    expect(screen.getByLabelText('To')).toHaveValue('84.49')
    expect(screen.getByLabelText('Step')).toBeInTheDocument()
  })

  it('fetches no ladder until there is a range for it', () => {
    // With no price in effect there is no anchor, so no range is implied and
    // no rung is shown as though it meant something.
    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={vi.fn()}
        productId="product-1"
        channelId="channel-1"
        currentPrice={null}
      />
    )

    expect(mocked.getPriceLadder).not.toHaveBeenCalled()
  })

  it('renders nothing while no channel is chosen', () => {
    renderDialog(
      <PriceFinderDialog
        open
        onOpenChange={vi.fn()}
        productId="product-1"
        channelId={null}
      />
    )

    expect(screen.queryByRole('tab', { name: /from a target margin/i })).not.toBeInTheDocument()
  })
})
