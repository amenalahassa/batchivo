/**
 * The designer list shows membership costs in the books currency
 * (bug hardcoded-gbp-outside-pricing): it formatted them with a hardcoded `£`.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DesignerList } from './DesignerList'

vi.mock('@/lib/api/designers', () => ({
  listDesigners: vi.fn().mockResolvedValue({
    total: 1,
    designers: [
      {
        id: 'd-1',
        name: 'Wyrmworks',
        slug: 'wyrmworks',
        membership_cost: '12.00',
        is_active: true,
        product_count: 3,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
  }),
  createDesigner: vi.fn(),
  updateDesigner: vi.fn(),
  deleteDesigner: vi.fn(),
}))
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'CAD', symbol: 'CA$' } }),
}))

describe('DesignerList currency', () => {
  it('formats the membership cost in the books currency', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <DesignerList />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('CA$12.00')).toBeInTheDocument()
    expect(screen.queryByText(/£/)).not.toBeInTheDocument()
  })
})
