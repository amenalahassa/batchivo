/**
 * The fee preview is reachable (T246, contracts/pricing-api.md, FR-021c).
 *
 * The panel sends the order as typed, shows the itemised stack with a bound
 * clamp and an expected fee, and names a date no rule covers rather than
 * reading it as no fees.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { FeePreviewPanel } from './FeePreviewPanel'
import { feeRulesApi } from '@/lib/api/feeRules'
import type { FeeCharge, FeePreviewResponse } from '@/types/pricing'

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: { preview: vi.fn() },
}))

const api = vi.mocked(feeRulesApi)

function charge(overrides: Partial<FeeCharge> = {}): FeeCharge {
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

function response(overrides: Partial<FeePreviewResponse> = {}): FeePreviewResponse {
  return {
    charges: [
      charge(),
      charge({ name: 'processing cap', amount: '2.00', clamp_applied: 'max' }),
      charge({ name: 'offsite ads', amount: '1.95', is_expected: true, incidence_pct: '15' }),
    ],
    total: '8.17',
    periodic: [],
    periodic_total: '0.00',
    bound_clamps: ['processing cap'],
    as_of: '2026-10-24',
    revenue_tax_exclusive: '64.99',
    tax_exclusive_derived: false,
    incomplete_reasons: [],
    ...overrides,
  }
}

function renderPanel(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('FeePreviewPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.preview.mockResolvedValue(response())
  })

  it('previews an order as typed and shows the itemised stack', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<FeePreviewPanel channelId="channel-1" currencySymbol="CA$" />)

    await user.type(screen.getByLabelText('Item price'), '64.99')
    await user.type(screen.getByLabelText('Shipping charged'), '4.99')
    await user.click(screen.getByRole('button', { name: 'Preview fees' }))

    await waitFor(() => expect(api.preview).toHaveBeenCalled())
    expect(api.preview).toHaveBeenCalledWith('channel-1', {
      item_subtotal: '64.99',
      shipping_revenue: '4.99',
      quantity: 1,
    })
    expect(await screen.findByText('transaction')).toBeInTheDocument()
    expect(screen.getByTestId('fee-clamp-processing cap')).toHaveTextContent('Cap applied')
    expect(screen.getByTestId('fee-expected-offsite ads')).toHaveTextContent('Expected')
  })

  it('names a date no rule covers', async () => {
    const user = userEvent.setup({ delay: null })
    api.preview.mockResolvedValue(
      response({ incomplete_reasons: ['no fee rule covers 2026-10-24 for "listing"'] }),
    )
    renderPanel(<FeePreviewPanel channelId="channel-1" />)

    await user.type(screen.getByLabelText('Item price'), '10')
    await user.click(screen.getByRole('button', { name: 'Preview fees' }))

    expect(await screen.findByTestId('fee-preview-incomplete')).toHaveTextContent(
      'no fee rule covers',
    )
  })

  it('refuses a price that is not money, without asking the engine', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<FeePreviewPanel channelId="channel-1" />)

    await user.type(screen.getByLabelText('Item price'), '6.499')
    await user.click(screen.getByRole('button', { name: 'Preview fees' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter the item price')
    expect(api.preview).not.toHaveBeenCalled()
  })

  it('shows a refusal from the API', async () => {
    const user = userEvent.setup({ delay: null })
    api.preview.mockRejectedValue(new Error('Viewers cannot preview fees'))
    renderPanel(<FeePreviewPanel channelId="channel-1" />)

    await user.type(screen.getByLabelText('Item price'), '10')
    await user.click(screen.getByRole('button', { name: 'Preview fees' }))

    expect(await screen.findByText('Viewers cannot preview fees')).toBeInTheDocument()
  })
})
