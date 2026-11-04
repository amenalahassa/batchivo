/**
 * "Add standard packaging" (spec 006, T025): present items are ticked and
 * disabled, a previously removed one is marked so it can be cleared, and the
 * selection is what is applied.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { packagingCatalogueApi } from '@/lib/api/packagingCatalogue'
import type { CatalogueItem } from '@/types/packagingCatalogue'

import { AddCatalogueDialog } from './AddCatalogueDialog'

vi.mock('@/lib/api/packagingCatalogue', () => ({
  packagingCatalogueApi: { get: vi.fn(), apply: vi.fn() },
}))
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'CAD', symbol: 'C$' } }),
}))
const api = vi.mocked(packagingCatalogueApi)

function item(key: string, overrides: Partial<CatalogueItem> = {}): CatalogueItem {
  return {
    key,
    name: key,
    kind: 'box',
    inner_length_mm: '100',
    inner_width_mm: '100',
    inner_height_mm: '100',
    wall_mm: '3',
    empty_weight_grams: '60',
    fill_volume_ml: null,
    unit_of_measure: 'each',
    typical_cost: '0.95',
    source: 'catalogue estimate 2026-11',
    present: false,
    present_as: null,
    previously_removed: false,
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  api.get.mockResolvedValue({
    version: 1,
    as_of: '2026-11-01',
    currency: 'CAD',
    items: [
      item('box-cube-100', { present: true, present_as: 'row-1' }),
      item('box-cube-150', { previously_removed: true }),
      item('box-cube-200'),
    ],
  })
  api.apply.mockReset().mockResolvedValue({ added: [], skipped: [] })
})

describe('AddCatalogueDialog', () => {
  it('ticks and disables an item already present', async () => {
    renderDialog(<AddCatalogueDialog open onOpenChange={vi.fn()} />)
    const present = await screen.findByRole('checkbox', { name: 'box-cube-100' })
    expect(present).toBeDisabled()
    expect(present).toBeChecked()
    expect(screen.getByText('Already added')).toBeInTheDocument()
  })

  it('marks a previously removed item, selected so adding restores it', async () => {
    renderDialog(<AddCatalogueDialog open onOpenChange={vi.fn()} />)
    expect(await screen.findByText('Previously removed')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'box-cube-150' })).toBeChecked()
  })

  it('applies the selection, without what the operator cleared', async () => {
    const onOpenChange = vi.fn()
    renderDialog(<AddCatalogueDialog open onOpenChange={onOpenChange} />)
    fireEvent.click(await screen.findByRole('checkbox', { name: 'box-cube-150' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add 1 item' }))
    await waitFor(() => expect(api.apply).toHaveBeenCalledWith(['box-cube-200']))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('shows the typical cost in the books currency', async () => {
    renderDialog(<AddCatalogueDialog open onOpenChange={vi.fn()} />)
    expect((await screen.findAllByText('~C$0.95')).length).toBe(3)
  })
})
