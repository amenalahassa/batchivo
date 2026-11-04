/**
 * Opening a packaging consumable for the first time keeps its kind and
 * category (spec 006 walkthrough).
 *
 * The form rendered before the record filled it, so its selects mounted on
 * their fallbacks ("hardware", "not packaging"); Radix's hidden select then
 * wrote the value it mounted with back through `onValueChange`, over the
 * loaded one. Saving a catalogue box opened for the first time turned it into
 * hardware that was not packaging. The stand-in select below does what Radix
 * does: shortly after mounting, it reports the value it mounted with.
 */
import { useEffect, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { consumablesApi } from '@/lib/api/consumables'
import type { ConsumableTypeResponse } from '@/types/consumable'

import { EditConsumableDialog } from './EditConsumableDialog'

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children: ReactNode
    onValueChange?: (v: string) => void
    value?: string
  }) => {
    const mounted = value
    useEffect(() => {
      const timer = setTimeout(() => onValueChange?.(mounted ?? ''), 0)
      return () => clearTimeout(timer)
      // Only the value it mounted with, as Radix's hidden select reports it.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return (
      <select value={value ?? ''} onChange={(e) => onValueChange?.(e.target.value)}>
        {children}
      </select>
    )
  },
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))
vi.mock('@/lib/api/consumables', () => ({ consumablesApi: { get: vi.fn(), update: vi.fn() } }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'o@example.com', role: 'admin' }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'CAD', symbol: 'C$' } }),
}))

const BOX = {
  id: 'box-1',
  tenant_id: 't',
  sku: 'PKG-BOX-CUBE-150',
  name: 'Box cube 150',
  category: 'packaging',
  unit_of_measure: 'each',
  current_cost_per_unit: '1.2500',
  quantity_on_hand: 0,
  is_active: true,
  is_low_stock: false,
  stock_value: '0.00',
  packaging_kind: 'box',
  inner_length_mm: '150.0',
  inner_width_mm: '150.0',
  inner_height_mm: '150.0',
  wall_mm: '3.0',
  empty_weight_grams: '95.0',
  packaging_provenance: { inner_length_mm: 'assumed' },
  created_at: '2026-11-04T00:00:00Z',
  updated_at: '2026-11-04T00:00:00Z',
} as ConsumableTypeResponse

describe('EditConsumableDialog first open', () => {
  it('saves a box opened for the first time with its kind and category', async () => {
    vi.mocked(consumablesApi.get).mockResolvedValue(BOX)
    vi.mocked(consumablesApi.update).mockResolvedValue(BOX)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <EditConsumableDialog open onOpenChange={vi.fn()} consumableId="box-1" />
      </QueryClientProvider>,
    )

    await screen.findByDisplayValue('PKG-BOX-CUBE-150')
    // Let the selects report the value they mounted with.
    await new Promise((resolve) => setTimeout(resolve, 10))
    fireEvent.click(screen.getByRole('button', { name: /save|update/i }))

    await waitFor(() => expect(consumablesApi.update).toHaveBeenCalled())
    expect(consumablesApi.update).toHaveBeenCalledWith(
      'box-1',
      expect.objectContaining({ category: 'packaging', packaging_kind: 'box' }),
    )
  })
})
