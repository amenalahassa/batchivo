/**
 * The spool purchase price crosses the wire as a decimal string (task T209).
 *
 * `purchase_price` is the figure `landed_cost.py` allocates inbound shipping
 * across and `costing.py:cost_per_gram` divides by usable weight, so every
 * material line is priced from it. This dialog sent it through `parseFloat`,
 * a JSON number, while the type declares it `Money`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { EditSpoolDialog } from './EditSpoolDialog'
import { materialTypesApi, spoolsApi } from '@/lib/api/spools'
import type { SpoolResponse } from '@/types/spool'

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

vi.mock('@/lib/api/spools', () => ({
  spoolsApi: {
    get: vi.fn(),
    list: vi.fn(),
    update: vi.fn(),
  },
  materialTypesApi: {
    list: vi.fn(),
  },
}))

const spools = vi.mocked(spoolsApi)
const materials = vi.mocked(materialTypesApi)

function spool(overrides: Partial<SpoolResponse> = {}): SpoolResponse {
  return {
    id: 'spool-uuid',
    tenant_id: 'tenant-uuid',
    spool_id: 'FIL-001',
    material_type_id: 'pla-uuid',
    material_type_code: 'PLA',
    material_type_name: 'PLA',
    brand: 'Bambu',
    color: 'Black',
    finish: null,
    initial_weight: 1000,
    current_weight: 800,
    empty_spool_weight: null,
    purchase_date: null,
    purchase_price: '8.30',
    supplier: null,
    purchased_quantity: 1,
    spools_remaining: 1,
    storage_location: null,
    notes: null,
    is_active: true,
    remaining_weight: 800,
    remaining_percentage: 80,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as SpoolResponse
}

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('EditSpoolDialog purchase price', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    spools.get.mockResolvedValue(spool())
    spools.list.mockResolvedValue({ spools: [], total: 0, page: 1, page_size: 100 } as never)
    spools.update.mockResolvedValue(spool())
    materials.list.mockResolvedValue([{ id: 'pla-uuid', name: 'PLA', code: 'PLA' } as never])
    vi.spyOn(window, 'alert').mockImplementation(() => {})
  })

  it('sends the typed price as a decimal string, never a number', async () => {
    renderDialog(<EditSpoolDialog open onOpenChange={() => {}} spoolId="spool-uuid" />)

    const price = await screen.findByLabelText('Price')
    await waitFor(() => expect(price).toHaveValue(8.3))

    fireEvent.change(price, { target: { value: '24.990' } })
    fireEvent.click(screen.getByRole('button', { name: /update spool/i }))

    await waitFor(() => expect(spools.update).toHaveBeenCalled())
    const sent = spools.update.mock.calls[0][1]
    // A double would have arrived as 24.99, its trailing digit and its type gone.
    expect(sent.purchase_price).toBe('24.990')
    expect(typeof sent.purchase_price).toBe('string')
  })

  it('keeps an untouched stored price exactly as the server sent it', async () => {
    renderDialog(<EditSpoolDialog open onOpenChange={() => {}} spoolId="spool-uuid" />)

    await waitFor(() => expect(screen.getByLabelText('Price')).toHaveValue(8.3))
    fireEvent.click(screen.getByRole('button', { name: /update spool/i }))

    await waitFor(() => expect(spools.update).toHaveBeenCalled())
    expect(spools.update.mock.calls[0][1].purchase_price).toBe('8.30')
  })

  it('clears the price to nothing rather than to zero', async () => {
    renderDialog(<EditSpoolDialog open onOpenChange={() => {}} spoolId="spool-uuid" />)

    const price = await screen.findByLabelText('Price')
    await waitFor(() => expect(price).toHaveValue(8.3))
    fireEvent.change(price, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /update spool/i }))

    await waitFor(() => expect(spools.update).toHaveBeenCalled())
    expect(spools.update.mock.calls[0][1].purchase_price).toBeUndefined()
  })
})
