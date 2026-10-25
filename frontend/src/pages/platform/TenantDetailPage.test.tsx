/**
 * The platform tenant page labels revenue in the tenant's own currency
 * (bug hardcoded-gbp-outside-pricing): it showed every tenant's revenue in `£`.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TenantDetailPage } from './TenantDetailPage'

vi.mock('@/components/platform/PlatformLayout', () => ({
  PlatformLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/hooks/usePlatformAdmin', () => ({
  useTenantDetail: () => ({
    data: {
      id: 't-1',
      name: 'Maple Makers',
      slug: 'maple-makers',
      tenant_type: 'three_d_print',
      currency_code: 'CAD',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      settings: null,
      user_count: 2,
      product_count: 5,
      order_count: 9,
      total_revenue: '1234.50',
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useDeactivateTenant: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useReactivateTenant: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('@/hooks/useImpersonation', () => ({
  useImpersonation: () => ({ startImpersonation: vi.fn(), isLoading: false }),
}))

describe('TenantDetailPage currency', () => {
  it("labels total revenue in the tenant's currency", () => {
    render(<TenantDetailPage />)

    expect(screen.getByText(/CA\$1,?234\.50/)).toBeInTheDocument()
    expect(screen.queryByText(/£/)).not.toBeInTheDocument()
  })
})
