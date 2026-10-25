/**
 * The consumable cost per unit crosses the wire as a decimal string (T210).
 *
 * The edit screen writes the same `current_cost_per_unit` the costing engine
 * reads for a linked packaging consumable, and it too sent `parseFloat`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { EditConsumableDialog } from './EditConsumableDialog'
import { consumablesApi } from '@/lib/api/consumables'
import type { ConsumableTypeResponse } from '@/types/consumable'

// Radix Select's hidden native <select> reports an empty value in jsdom and
// blanks the material type before submit; a native select stands in for it.
vi.mock('@/components/ui/select', () => ({
  Select: ({ children, onValueChange, value }: { children: ReactNode; onValueChange?: (v: string) => void; value?: string }) => (
    <select value={value ?? ''} onChange={(e) => onValueChange?.(e.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))

vi.mock('@/lib/api/consumables', () => ({
  consumablesApi: {
    get: vi.fn(),
    update: vi.fn(),
  },
}))

const api = vi.mocked(consumablesApi)

function consumable(overrides: Partial<ConsumableTypeResponse> = {}): ConsumableTypeResponse {
  return {
    id: 'consumable-uuid',
    tenant_id: 'tenant-uuid',
    sku: 'COM-001',
    name: 'Magnet 3x1',
    description: null,
    category: 'hardware',
    unit_of_measure: 'each',
    current_cost_per_unit: '0.0450',
    quantity_on_hand: 100,
    reorder_point: null,
    reorder_quantity: null,
    preferred_supplier: null,
    supplier_sku: null,
    supplier_url: null,
    typical_lead_days: null,
    is_active: true,
    is_low_stock: false,
    stock_value: '4.50',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

// The role the signed-in user holds; each test starts as an admin (T238).
const auth = vi.hoisted(() => ({ role: 'admin', symbol: '£' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({
    user: { email: 'operator@example.com', role: auth.role, currency_symbol: auth.symbol },
    logout: vi.fn(),
  })
  return { useAuth: session, useOptionalAuth: session }
})
beforeEach(() => {
  auth.role = 'admin'
  auth.symbol = '£'
})

describe('EditConsumableDialog cost per unit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue(consumable())
    api.update.mockResolvedValue(consumable())
    vi.spyOn(window, 'alert').mockImplementation(() => {})
  })

  it('sends the typed cost as a decimal string, never a number', async () => {
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    const cost = await screen.findByLabelText(/Cost per Unit/)
    await waitFor(() => expect(cost).toHaveValue(0.045))
    fireEvent.change(cost, { target: { value: '0.1000' } })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(api.update).toHaveBeenCalled())
    const sent = api.update.mock.calls[0][1]
    expect(sent.current_cost_per_unit).toBe('0.1000')
    expect(typeof sent.current_cost_per_unit).toBe('string')
  })

  it('keeps an untouched stored cost exactly as the server sent it', async () => {
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    await waitFor(() => expect(screen.getByLabelText(/Cost per Unit/)).toHaveValue(0.045))
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(api.update).toHaveBeenCalled())
    expect(api.update.mock.calls[0][1].current_cost_per_unit).toBe('0.0450')
  })

  it('clears the cost to null rather than to zero', async () => {
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    const cost = await screen.findByLabelText(/Cost per Unit/)
    await waitFor(() => expect(cost).toHaveValue(0.045))
    fireEvent.change(cost, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(api.update).toHaveBeenCalled())
    expect(api.update.mock.calls[0][1].current_cost_per_unit).toBeNull()
  })
})

describe('EditConsumableDialog for a viewer', () => {
  it('shows the stored cost but will not save a change', async () => {
    auth.role = 'viewer'
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    const cost = await screen.findByLabelText(/Cost per Unit/)
    await waitFor(() => expect(cost).toHaveValue(0.045))
    expect(cost).toBeDisabled()
    expect(screen.getByTestId('read-only-notice')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
  })
})

describe('EditConsumableDialog when a purchase prices the unit (T277)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue(
      consumable({
        current_cost_per_unit: '0.142857142857',
        priced_by_purchase_id: 'purchase-uuid',
        priced_by_purchase_date: '2026-06-01',
      }),
    )
    api.update.mockResolvedValue(consumable())
  })

  it('shows the cost read-only with the purchase it came from', async () => {
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    const cost = await screen.findByLabelText(/Cost per Unit/)
    expect(cost).toBeDisabled()
    expect(await screen.findByTestId('unit-cost-from-purchase')).toHaveTextContent('2026-06-01')
  })

  it('does not send a unit cost the purchase owns', async () => {
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    await screen.findByTestId('unit-cost-from-purchase')
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(api.update).toHaveBeenCalled())
    expect(api.update.mock.calls[0][1]).not.toHaveProperty('current_cost_per_unit')
  })
})

describe('EditConsumableDialog currency (T276)', () => {
  it('labels the unit cost in the books currency', async () => {
    auth.symbol = 'C$'
    api.get.mockResolvedValue(consumable())
    renderDialog(<EditConsumableDialog open onOpenChange={() => {}} consumableId="consumable-uuid" />)

    expect(await screen.findByLabelText('Cost per Unit (C$)')).toBeInTheDocument()
  })
})
