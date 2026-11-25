/**
 * A viewer meets the new-spool form disabled, not missing (T238, FR-007c).
 *
 * A spool's purchase price is an operational figure the costing engine reads,
 * so recording one needs a member, admin or owner, as the API enforces. The
 * form is still shown to a viewer, with the reason, rather than hidden.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { AddSpoolDialog } from './AddSpoolDialog'
import { materialTypesApi, spoolsApi } from '@/lib/api/spools'

vi.mock('@/lib/api/spools', () => ({
  spoolsApi: { list: vi.fn(), create: vi.fn() },
  materialTypesApi: { list: vi.fn() },
}))

vi.mock('@/hooks/useSKU', () => ({
  useNextSKU: () => ({ nextSKU: 'FIL-001', isLoading: false, refetch: vi.fn() }),
}))

vi.mock('./SpoolmanDBPicker', () => ({ SpoolmanDBPicker: () => null }))

const auth = vi.hoisted(() => ({ role: 'admin', currency_code: 'GBP', currency_symbol: '£' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'operator@example.com', ...auth }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('AddSpoolDialog by role', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'admin'
    auth.currency_code = 'GBP'
    auth.currency_symbol = '£'
    vi.mocked(materialTypesApi.list).mockResolvedValue([])
    vi.mocked(spoolsApi.list).mockResolvedValue({ spools: [], total: 0, page: 1, page_size: 100 } as never)
  })

  it('shows a viewer the form disabled, with the reason', async () => {
    auth.role = 'viewer'
    renderDialog(<AddSpoolDialog open onOpenChange={() => {}} />)

    expect(await screen.findByTestId('read-only-notice')).toBeInTheDocument()
    expect(screen.getByLabelText(/brand/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: /create spool/i })).toBeDisabled()
  })

  it('lets a member record a spool', async () => {
    auth.role = 'member'
    renderDialog(<AddSpoolDialog open onOpenChange={() => {}} />)

    expect(await screen.findByLabelText(/brand/i)).toBeEnabled()
    expect(screen.queryByTestId('read-only-notice')).not.toBeInTheDocument()
  })

  it('prices the spool in the tenant’s own currency, with nothing to choose', async () => {
    // The selector offered GBP, USD and EUR, started at GBP whatever the
    // tenant kept its books in, and sent none of them (T231).
    auth.currency_code = 'CAD'
    auth.currency_symbol = 'CA$'
    renderDialog(<AddSpoolDialog open onOpenChange={() => {}} />)

    expect(await screen.findByLabelText('Total Price (CAD)')).toBeInTheDocument()
    expect(screen.queryByLabelText('Currency')).not.toBeInTheDocument()
  })
})
