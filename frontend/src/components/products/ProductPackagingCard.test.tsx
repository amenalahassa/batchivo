/**
 * The product's packaging card (spec 006, T020, T038, T053): it links to the
 * Packaging page, and its postage service override lists only the services
 * whose size limits take the product's box.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { consumablesApi } from '@/lib/api/consumables'
import { updateProduct, type ProductDetail } from '@/lib/api/products'

import { ProductPackagingCard } from './ProductPackagingCard'

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
    disabled,
  }: {
    children: ReactNode
    onValueChange?: (v: string) => void
    value?: string
    disabled?: boolean
  }) => (
    <select
      aria-label="Postage service"
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onValueChange?.(e.target.value)}
    >
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
vi.mock('./DimensionsEditor', () => ({ DimensionsEditor: () => null }))
vi.mock('./PackagingSuggestions', () => ({ PackagingSuggestions: () => null }))
vi.mock('@/lib/api/consumables', () => ({ consumablesApi: { get: vi.fn() } }))
vi.mock('@/lib/api/products', () => ({ updateProduct: vi.fn() }))
vi.mock('@/hooks/usePostageCatalogue', () => ({
  useCarriers: () => ({
    carriers: {
      carriers: [
        {
          key: 'canada_post',
          name: 'Canada Post',
          services: [
            { key: 'small_packet', name: 'Small Packet' },
            { key: 'expedited_parcel', name: 'Expedited Parcel' },
            { key: 'lettermail', name: 'Lettermail' },
          ],
        },
      ],
    },
  }),
}))

function product(overrides: Partial<ProductDetail> = {}): ProductDetail {
  return {
    id: 'p1',
    sku: 'DRAGON',
    name: 'Dragon',
    packaging_consumable_id: 'box-1',
    postage_service: null,
    variants: [],
    ...overrides,
  } as unknown as ProductDetail
}

function renderCard(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(consumablesApi.get).mockResolvedValue({
    id: 'box-1',
    fits_services: ['canada_post:small_packet', 'canada_post:expedited_parcel'],
  } as never)
  vi.mocked(updateProduct).mockReset().mockResolvedValue({} as never)
})

describe('ProductPackagingCard', () => {
  it('links to the Packaging page', () => {
    renderCard(<ProductPackagingCard product={product()} canEdit />)
    expect(screen.getByRole('link', { name: 'Packaging page' })).toHaveAttribute(
      'href',
      '/packaging',
    )
  })

  it('offers only the services that take the box, plus the shop default', async () => {
    renderCard(<ProductPackagingCard product={product()} canEdit />)
    const select = screen.getByRole('combobox', { name: 'Postage service' })
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(3))
    const names = within(select)
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(names).toEqual([
      'Shop default',
      'Canada Post Small Packet',
      'Canada Post Expedited Parcel',
    ])
    expect(names).not.toContain('Canada Post Lettermail')
  })

  it('saves the chosen service, and clears it back to the shop default', async () => {
    renderCard(<ProductPackagingCard product={product()} canEdit />)
    const select = screen.getByRole('combobox', { name: 'Postage service' })
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(3))
    fireEvent.change(select, { target: { value: 'canada_post:expedited_parcel' } })
    await waitFor(() =>
      expect(updateProduct).toHaveBeenCalledWith('p1', {
        postage_service: 'canada_post:expedited_parcel',
      }),
    )
    fireEvent.change(select, { target: { value: '__shop_default__' } })
    await waitFor(() => expect(updateProduct).toHaveBeenLastCalledWith('p1', { postage_service: null }))
  })

  it('says when the saved service no longer takes the box', async () => {
    renderCard(
      <ProductPackagingCard product={product({ postage_service: 'canada_post:lettermail' })} canEdit />,
    )
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Canada Post Lettermail does not take this product',
    )
  })

  it('is read-only without the role', async () => {
    renderCard(<ProductPackagingCard product={product()} canEdit={false} />)
    expect(screen.getByRole('combobox', { name: 'Postage service' })).toBeDisabled()
  })

  it('asks for a box before a service', () => {
    renderCard(<ProductPackagingCard product={product({ packaging_consumable_id: null })} canEdit />)
    expect(screen.getByTestId('postage-service-none')).toBeInTheDocument()
  })
})
