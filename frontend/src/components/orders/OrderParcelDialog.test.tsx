/**
 * Confirming an order's parcels at dispatch (T065).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { consumablesApi } from '@/lib/api/consumables'
import { confirmOrderParcels, getOrderPackagingSuggestions } from '@/lib/api/packaging'
import { OrderParcelDialog } from './OrderParcelDialog'
import { toConfirmInput } from '@/lib/packaging'

vi.mock('@/lib/api/packaging', () => ({
  getOrderPackagingSuggestions: vi.fn(),
  confirmOrderParcels: vi.fn(),
}))
vi.mock('@/lib/api/consumables', () => ({ consumablesApi: { list: vi.fn() } }))
// A native select stands in for Radix's, which jsdom cannot drive.
vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children: ReactNode
    onValueChange?: (v: string) => void
    value?: string
  }) => (
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

const suggest = vi.mocked(getOrderPackagingSuggestions)
const confirm = vi.mocked(confirmOrderParcels)
const list = vi.mocked(consumablesApi.list)

function consumable(id: string, name: string, kind: string) {
  return { id, name, packaging_kind: kind } as never
}

function renderDialog(onContinue = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <OrderParcelDialog
        orderId="order-1"
        orderNumber="ORD-1"
        open
        onOpenChange={() => {}}
        onContinue={onContinue}
      />
    </QueryClientProvider>,
  )
  return onContinue
}

describe('OrderParcelDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    suggest.mockResolvedValue({
      parcels: [
        {
          consumable_id: 'box-m',
          name: 'Box M',
          contents: [{ product_id: 'p-1', sku: 'DRG-01', quantity: 2 }],
          outer_mm: { length_mm: '206.0', width_mm: '106.0', height_mm: '66.0' },
          packed_weight_grams: '258.0',
          void_fill: { consumable_id: 'fill', name: 'Paper fill', quantity: 2 },
        },
      ],
      estimated_postage: { amount: '3.95', zone: 'domestic', reason: null, is_estimate: true },
      warnings: [],
    })
    list.mockResolvedValue({
      total: 3,
      page: 1,
      page_size: 100,
      consumables: [
        consumable('box-m', 'Box M', 'box'),
        consumable('box-l', 'Box L', 'box'),
        consumable('fill', 'Paper fill', 'void_fill'),
      ],
    })
    confirm.mockResolvedValue({
      parcels: [
        {
          id: 'parcel-1',
          sequence: 1,
          outer_length_mm: '206.0',
          outer_width_mm: '106.0',
          outer_height_mm: '66.0',
          packed_weight_grams: '258.0',
          confirmed_at: '2026-10-25T10:00:00Z',
          items: [
            { consumable_id: 'box-l', name: 'Box L', quantity: 1 },
            { consumable_id: 'fill', name: 'Paper fill', quantity: 3 },
          ],
        },
      ],
      postage: { amount: '3.95', zone: 'domestic', reason: null, is_estimate: false },
      warnings: [{ code: 'stock_below_zero', consumable_id: 'box-l', on_hand: -1 }],
    })
  })

  it('starts from the suggestion with the postage marked an estimate', async () => {
    renderDialog()
    expect(await screen.findByText('2 × DRG-01')).toBeInTheDocument()
    expect(screen.getByTestId('estimated-postage')).toHaveTextContent('3.95')
    expect(screen.getByText('estimate')).toBeInTheDocument()
  })

  it('confirms the edited parcel and shows what was stored and the stock warning', async () => {
    const onContinue = renderDialog()
    await screen.findByText('2 × DRG-01')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Box L' })).toBeInTheDocument())

    const container = screen.getByRole('option', { name: 'Box L' }).closest('select')!
    fireEvent.change(container, { target: { value: 'box-l' } })
    fireEvent.change(screen.getByLabelText('Void fill (units)'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm parcels' }))

    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(confirm.mock.calls[0]).toEqual([
      'order-1',
      {
        parcels: [
          {
            items: [
              { consumable_id: 'box-l', quantity: 1 },
              { consumable_id: 'fill', quantity: 3 },
            ],
            contents: null,
          },
        ],
      },
    ])
    expect(await screen.findByTestId('confirmed-parcels')).toHaveTextContent('1 × Box L')
    expect(screen.getByText(/Stock of Box L is now -1/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Continue to shipping' }))
    expect(onContinue).toHaveBeenCalled()
  })

  it('can be skipped', async () => {
    const onContinue = renderDialog()
    await screen.findByText('2 × DRG-01')
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
    expect(onContinue).toHaveBeenCalled()
    expect(confirm).not.toHaveBeenCalled()
  })

  it('names a line without dimensions', async () => {
    suggest.mockResolvedValue({
      parcels: [],
      estimated_postage: { amount: null, zone: null, reason: 'unknown', is_estimate: true },
      warnings: [{ code: 'dimensions_required', sku: 'NODIMS' }],
    })
    renderDialog()
    expect(await screen.findByText(/NODIMS has no dimensions/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm parcels' })).toBeDisabled()
  })
})

describe('toConfirmInput', () => {
  it('sends each parcel its contents when there are several', () => {
    const input = toConfirmInput([
      { containerId: 'a', fillId: null, fillQuantity: 0, contents: [{ sku: 'X', quantity: 1 }] },
      { containerId: 'b', fillId: null, fillQuantity: 0, contents: [{ sku: 'Y', quantity: 1 }] },
    ])
    expect(input.parcels.map((p) => p.contents)).toEqual([
      [{ sku: 'X', quantity: 1 }],
      [{ sku: 'Y', quantity: 1 }],
    ])
    expect(input.parcels[0].items).toEqual([{ consumable_id: 'a', quantity: 1 }])
  })
})
