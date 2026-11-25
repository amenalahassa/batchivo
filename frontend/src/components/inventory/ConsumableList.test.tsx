/**
 * The consumable list shows costs in the books currency (task T276).
 *
 * It formatted every unit cost and stock value with a hardcoded `£`, so a
 * workshop keeping its books in Canadian dollars was shown pounds.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { consumablesApi } from '@/lib/api/consumables'

import { ConsumableList } from './ConsumableList'

vi.mock('@/lib/api/consumables', () => ({
  consumablesApi: {
    list: vi.fn().mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 20,
      consumables: [
        {
          id: 'c-1',
          tenant_id: 't-1',
          sku: 'BOX-S',
          name: 'Small box',
          description: null,
          category: 'packaging',
          unit_of_measure: 'each',
          current_cost_per_unit: '0.4500',
          quantity_on_hand: 10,
          reorder_point: null,
          reorder_quantity: null,
          preferred_supplier: null,
          supplier_sku: null,
          supplier_url: null,
          typical_lead_days: null,
          is_active: true,
          is_low_stock: false,
          stock_value: '4.50',
          packaging_kind: 'box',
          packaging_incomplete: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    }),
    delete: vi.fn(),
  },
}))
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'CAD', symbol: 'C$' } }),
}))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'o@example.com', role: 'admin' }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})

describe('ConsumableList currency (T276)', () => {
  it('formats the unit cost and stock value in the books currency', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConsumableList />
      </QueryClientProvider>,
    )

    expect((await screen.findAllByText('C$0.45')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('C$4.50').length).toBeGreaterThan(0)
    expect(screen.queryByText(/£/)).not.toBeInTheDocument()
  })
})

describe('ConsumableList packaging (T029)', () => {
  it('marks a box without its inner size as incomplete', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConsumableList />
      </QueryClientProvider>,
    )

    expect((await screen.findAllByText('Incomplete')).length).toBeGreaterThan(0)
  })
})

describe('ConsumableList excludes packaging (spec 006, T012)', () => {
  it('asks for consumables that are not packaging and shows no box', async () => {
    const list = vi.mocked(consumablesApi.list)
    // The API filters; the mock answers as it would for exclude_packaging=true.
    list.mockResolvedValue({ total: 0, page: 1, page_size: 20, consumables: [] })
    list.mockClear()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConsumableList />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('No consumables found')).toBeInTheDocument()
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ exclude_packaging: true }))
    expect(screen.queryByText('Small box')).not.toBeInTheDocument()
  })

  it('points to the Packaging page', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConsumableList />
      </QueryClientProvider>,
    )

    const link = await screen.findByRole('link', { name: 'Packaging page' })
    expect(link).toHaveAttribute('href', '/packaging')
  })
})
