/**
 * The Packaging page's list (spec 006, US1, T011).
 *
 * It asks for packaging kinds only and shows, per kind, the figures that
 * kind needs; a box without its inner size says it is incomplete; a catalogue
 * default is badged; "Add box" opens the form in Box mode; a viewer gets no
 * add, edit or delete controls.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { consumablesApi } from '@/lib/api/consumables'
import type { ConsumableTypeResponse } from '@/types/consumable'

import { PackagingList } from './PackagingList'

const auth = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'o@example.com', role: auth.role }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'CAD', symbol: 'C$' } }),
}))
vi.mock('@/hooks/usePostageCatalogue', () => ({
  useCarriers: () => ({
    carriers: {
      carriers: [
        {
          key: 'canada_post',
          name: 'Canada Post',
          services: [{ key: 'small_packet', name: 'Small Packet' }],
        },
      ],
    },
  }),
}))
vi.mock('./CatalogueNotice', () => ({ CatalogueNotice: () => null }))
vi.mock('./AddCatalogueDialog', () => ({
  AddCatalogueDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="catalogue-dialog" /> : null,
}))
vi.mock('@/components/inventory/AddConsumableDialog', () => ({
  AddConsumableDialog: ({
    open,
    presetKind,
    packagingOnly,
  }: {
    open: boolean
    presetKind?: string
    packagingOnly?: boolean
  }) =>
    open ? (
      <div data-testid="add-dialog" data-kind={presetKind} data-packaging-only={String(packagingOnly)} />
    ) : null,
}))
vi.mock('@/components/inventory/EditConsumableDialog', () => ({ EditConsumableDialog: () => null }))
vi.mock('@/components/inventory/DeleteConsumableDialog', () => ({
  DeleteConsumableDialog: () => null,
}))
vi.mock('@/lib/api/consumables', () => ({ consumablesApi: { list: vi.fn() } }))

function row(overrides: Partial<ConsumableTypeResponse>): ConsumableTypeResponse {
  return {
    id: overrides.sku ?? 'id',
    tenant_id: 't',
    sku: 'X',
    name: 'X',
    unit_of_measure: 'each',
    quantity_on_hand: 0,
    is_active: true,
    is_low_stock: false,
    stock_value: '0.00',
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    ...overrides,
  }
}

const BOX = row({
  sku: 'PKG-BOX-150',
  name: 'Box 150',
  packaging_kind: 'box',
  inner_length_mm: '150.0',
  inner_width_mm: '150.0',
  inner_height_mm: '150.0',
  wall_mm: '3.0',
  empty_weight_grams: '95.0',
  quantity_on_hand: 12,
  current_cost_per_unit: '1.2000',
  from_catalogue: true,
  cost_provenance: 'assumed',
  packaging_provenance: {
    inner_length_mm: 'assumed',
    inner_width_mm: 'assumed',
    inner_height_mm: 'assumed',
    wall_mm: 'measured',
  },
  fits_services: ['canada_post:small_packet'],
  used_by_products: [{ id: 'p1', sku: 'DRAGON', name: 'Ember Dragon' }],
})
const BARE_BOX = row({ sku: 'BOX-BARE', name: 'Bare box', packaging_kind: 'box', packaging_incomplete: true })
const FILL = row({ sku: 'PKG-FILL', name: 'Kraft paper', packaging_kind: 'void_fill', fill_volume_ml: '500' })

function renderList(node: ReactNode = <PackagingList />) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  auth.role = 'admin'
  vi.mocked(consumablesApi.list).mockResolvedValue({
    total: 3,
    page: 1,
    page_size: 100,
    consumables: [BOX, BARE_BOX, FILL],
  })
})

describe('PackagingList', () => {
  it('asks for packaging kinds only', async () => {
    renderList()
    await screen.findByText('Box 150')
    expect(consumablesApi.list).toHaveBeenCalledWith(
      expect.objectContaining({ packaging_kind: 'box,mailer,void_fill,wrap' }),
    )
  })

  it('shows a box with inner size, wall, empty weight, stock, cost, fits and used-by', async () => {
    renderList()
    const box = within(await screen.findByTestId('packaging-row-PKG-BOX-150'))
    expect(box.getByText(/150\.0 × 150\.0 × 150\.0 mm/)).toBeInTheDocument()
    expect(box.getByText(/3\.0 mm/)).toBeInTheDocument()
    expect(box.getByText(/95\.0 g/)).toBeInTheDocument()
    expect(box.getByText('12 each')).toBeInTheDocument()
    expect(box.getByText('C$1.20')).toBeInTheDocument()
    expect(box.getByText('Canada Post Small Packet')).toBeInTheDocument()
    expect(box.getByText('Ember Dragon')).toBeInTheDocument()
  })

  it('badges catalogue defaults but not measured figures', async () => {
    renderList()
    const box = within(await screen.findByTestId('packaging-row-PKG-BOX-150'))
    // The size and the cost are defaults; the wall was measured.
    expect(box.getAllByText('default')).toHaveLength(2)
  })

  it("marks an operator's own estimate as estimated, not as a catalogue default", async () => {
    vi.mocked(consumablesApi.list).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 100,
      consumables: [
        row({
          sku: 'MINE',
          name: 'My box',
          packaging_kind: 'box',
          inner_length_mm: '200.0',
          inner_width_mm: '150.0',
          inner_height_mm: '100.0',
          from_catalogue: false,
          packaging_provenance: { inner_length_mm: 'assumed' },
        }),
      ],
    })
    renderList()
    const mine = within(await screen.findByTestId('packaging-row-MINE'))
    // Only one side was estimated: the size says so, and nothing says "default".
    expect(mine.getByText('partly estimated')).toBeInTheDocument()
    expect(mine.queryByText(/default/)).not.toBeInTheDocument()
  })

  it('says a size is partly default once one side is measured', async () => {
    vi.mocked(consumablesApi.list).mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 100,
      consumables: [
        {
          ...BOX,
          packaging_provenance: {
            inner_length_mm: 'assumed',
            inner_width_mm: 'assumed',
            inner_height_mm: 'measured',
            wall_mm: 'measured',
          },
        },
      ],
    })
    renderList()
    const box = within(await screen.findByTestId('packaging-row-PKG-BOX-150'))
    expect(box.getByText('partly default')).toBeInTheDocument()
  })

  it('shows the fill volume for void fill', async () => {
    renderList()
    const fill = within(await screen.findByTestId('packaging-row-PKG-FILL'))
    expect(fill.getByText(/500 ml/)).toBeInTheDocument()
  })

  it('says a box without its inner size is incomplete, and why', async () => {
    renderList()
    const bare = within(await screen.findByTestId('packaging-row-BOX-BARE'))
    expect(bare.getByText(/Incomplete: inner size missing/)).toBeInTheDocument()
  })

  it('opens the form in box mode from "Add box"', async () => {
    renderList()
    await screen.findByText('Box 150')
    fireEvent.click(screen.getByRole('button', { name: 'Add box' }))
    const dialog = screen.getByTestId('add-dialog')
    expect(dialog).toHaveAttribute('data-kind', 'box')
    expect(dialog).toHaveAttribute('data-packaging-only', 'true')
  })

  it('opens the standard catalogue', async () => {
    renderList()
    await screen.findByText('Box 150')
    fireEvent.click(screen.getByRole('button', { name: 'Add standard packaging' }))
    expect(screen.getByTestId('catalogue-dialog')).toBeInTheDocument()
  })

  it('gives a viewer no add, edit or delete', async () => {
    auth.role = 'viewer'
    renderList()
    await screen.findByText('Box 150')
    expect(screen.queryByRole('button', { name: /^Add/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Delete/ })).not.toBeInTheDocument()
  })
})
