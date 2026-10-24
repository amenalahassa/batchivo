/**
 * A purchase can be recorded, and an existing one reopened (task T131).
 *
 * `FilamentPurchaseForm` was built and tested but imported nowhere, so FR-008a
 * — a purchase, not just a spool, is recordable — had no path through the
 * console, and with it went the landed per-gram cost the whole material line
 * rests on.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { FilamentPurchaseDialog } from './FilamentPurchaseDialog'
import { pricingApi } from '@/lib/api/pricing'
import type { FilamentPurchase } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    listFilamentPurchases: vi.fn(),
    getFilamentPurchase: vi.fn(),
    createFilamentPurchase: vi.fn(),
    updateFilamentPurchase: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)

function purchase(overrides: Partial<FilamentPurchase> = {}): FilamentPurchase {
  return {
    id: 'purchase-1',
    supplier: 'Filament Co',
    purchase_date: '2026-02-01',
    inbound_shipping_cost: '12.00',
    tax_amount: '0.00',
    tax_recoverable: false,
    order_reference: null,
    notes: null,
    spools: [],
    allocation_notes: [],
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

// The role the signed-in user holds; each test starts as an admin (T238).
const auth = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'operator@example.com', role: auth.role }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})
beforeEach(() => {
  auth.role = 'admin'
})

describe('FilamentPurchaseDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.listFilamentPurchases.mockResolvedValue({ purchases: [], total: 0, skip: 0, limit: 50 })
    mocked.getFilamentPurchase.mockResolvedValue(purchase())
  })

  it('opens on a blank form, so a purchase can be recorded', async () => {
    renderDialog(<FilamentPurchaseDialog open onOpenChange={vi.fn()} />)

    expect(await screen.findByLabelText(/shipping/i)).toBeInTheDocument()
    // Nothing is fetched for a purchase that does not exist yet.
    expect(mocked.getFilamentPurchase).not.toHaveBeenCalled()
  })

  it('says why a purchase is worth recording rather than a bare spool price', async () => {
    renderDialog(<FilamentPurchaseDialog open onOpenChange={vi.fn()} />)

    expect(
      await screen.findByText(/shipping split by weight/i)
    ).toBeInTheDocument()
  })

  it('lists what has been recorded and reopens one for correction', async () => {
    // The edge case under FR-008: a spool added later re-runs the allocation
    // for every spool in the purchase, so correcting one must be reachable.
    mocked.listFilamentPurchases.mockResolvedValue({
      purchases: [purchase({ id: 'purchase-9', supplier: 'Spool World' })],
      total: 1,
      skip: 0,
      limit: 50,
    })

    const user = userEvent.setup({ delay: null })
    renderDialog(<FilamentPurchaseDialog open onOpenChange={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: /spool world/i }))

    await waitFor(() => {
      expect(mocked.getFilamentPurchase).toHaveBeenCalledWith('purchase-9')
    })
  })

  it('shows the amounts in the tenant’s own currency', async () => {
    mocked.listFilamentPurchases.mockResolvedValue({
      purchases: [purchase({ inbound_shipping_cost: '12.00' })],
      total: 1,
      skip: 0,
      limit: 50,
    })

    renderDialog(<FilamentPurchaseDialog open onOpenChange={vi.fn()} currencySymbol="CA$" />)

    expect(await screen.findByText(/CA\$12\.00 shipping/)).toBeInTheDocument()
  })
})

describe('FilamentPurchaseDialog for a viewer', () => {
  it('opens the form read-only, saying why', async () => {
    auth.role = 'viewer'
    renderDialog(<FilamentPurchaseDialog open onOpenChange={vi.fn()} />)

    expect(await screen.findByTestId('read-only-notice')).toBeInTheDocument()
  })
})
