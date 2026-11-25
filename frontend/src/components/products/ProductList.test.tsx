/**
 * What the product list is allowed to say about a cost.
 *
 * Two changes are pinned here.
 *
 * **No SRP.** The list rendered `suggested_price` -- the backend's
 * `total_make_cost * 2.5` -- as "SRP" and as a column headed "SRP (2.5x)".
 * No operator configured that markup, and cost plus a flat markup lands
 * several points below the margin actually asked for. A price comes from the
 * solver and the ladder on the pricing editor (FR-007/FR-048).
 *
 * **An incomplete cost says so.** The row now carries the engine's
 * `incomplete_reasons`, so a product missing its print time or its machine
 * rate is not shown as a finished figure built from a zero (FR-019, US2).
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { render } from '@/test/test-utils'
import { ProductList } from './ProductList'
import { listProducts } from '@/lib/api/products'
import type { Product, ProductListResponse } from '@/lib/api/products'

vi.mock('@/lib/api/products', () => ({
  listProducts: vi.fn(),
}))

const mockListProducts = listProducts as Mock

function makeProduct(overrides: Partial<Product> = {}): Product {
  return {
    id: 'product-1',
    tenant_id: 'tenant-1',
    sku: 'DRG-001',
    name: 'Articulated Dragon',
    packaging_cost: '0.40',
    packaging_quantity: 1,
    assembly_minutes: 0,
    units_in_stock: 3,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    total_make_cost: '12.34',
    incomplete_reasons: [],
    shop_visible: true,
    is_featured: false,
    is_dragon: true,
    print_to_order: false,
    ...overrides,
  }
}

function listOf(...products: Product[]): ProductListResponse {
  return { products, total: products.length, skip: 0, limit: 50 }
}

describe('ProductList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('the markup-derived price is gone', () => {
    it('renders no SRP figure for a product', async () => {
      mockListProducts.mockResolvedValue(listOf(makeProduct()))

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getAllByText('Articulated Dragon').length).toBeGreaterThan(0)
      })

      expect(screen.queryByText(/SRP/i)).not.toBeInTheDocument()
    })

    it('renders no SRP column header', async () => {
      mockListProducts.mockResolvedValue(listOf(makeProduct()))

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getByText('Make Cost')).toBeInTheDocument()
      })

      expect(screen.queryByText(/2\.5/)).not.toBeInTheDocument()
    })

    it('still shows the engine make cost', async () => {
      mockListProducts.mockResolvedValue(listOf(makeProduct({ total_make_cost: '12.34' })))

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getAllByText(/£12\.34/).length).toBeGreaterThan(0)
      })
    })
  })

  describe('an incompletely costed product says so', () => {
    it('shows the badge when the engine reported a reason', async () => {
      mockListProducts.mockResolvedValue(
        listOf(
          makeProduct({
            incomplete_reasons: ['no print time is recorded, so this item carries no machine charge'],
          }),
        ),
      )

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getAllByTestId('incomplete-cost-badge').length).toBeGreaterThan(0)
      })
    })

    it('names the reason to a screen reader, not only on hover', async () => {
      mockListProducts.mockResolvedValue(
        listOf(makeProduct({ incomplete_reasons: ['no machine rate is configured'] })),
      )

      render(<ProductList />)

      await waitFor(() => {
        expect(
          screen.getAllByLabelText(/Incompletely costed: no machine rate is configured/).length,
        ).toBeGreaterThan(0)
      })
    })

    it('shows no badge for a completely costed product', async () => {
      mockListProducts.mockResolvedValue(listOf(makeProduct({ incomplete_reasons: [] })))

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getAllByText('Articulated Dragon').length).toBeGreaterThan(0)
      })

      expect(screen.queryByTestId('incomplete-cost-badge')).not.toBeInTheDocument()
    })

    it('shows no badge when the API sent no flag at all', async () => {
      // An older backend, or a payload that predates the field: absent is not
      // the same as "incomplete", and must not raise.
      mockListProducts.mockResolvedValue(listOf(makeProduct({ incomplete_reasons: undefined })))

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getAllByText('Articulated Dragon').length).toBeGreaterThan(0)
      })

      expect(screen.queryByTestId('incomplete-cost-badge')).not.toBeInTheDocument()
    })
  })

  describe('money is rendered exactly', () => {
    it('renders a cost whose decimal string a float would round differently', async () => {
      // 0.145 is not representable in binary: the old renderer put the string
      // through parseFloat and could land a cent away from the exact value
      // the engine computed. formatMoney rounds half-up in string space.
      mockListProducts.mockResolvedValue(listOf(makeProduct({ total_make_cost: '2.145' })))

      render(<ProductList />)

      await waitFor(() => {
        expect(screen.getAllByText(/£2\.15/).length).toBeGreaterThan(0)
      })
    })
  })
})
