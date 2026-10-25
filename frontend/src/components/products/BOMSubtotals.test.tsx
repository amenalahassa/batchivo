/**
 * The bill-of-materials subtotals are the engine's, not a browser re-sum (T263).
 *
 * Each line's unit cost arrives quantized; the breakdown's `models_cost` and
 * `child_products_cost` do not. Summing the quantized lines times quantity can
 * miss the engine's figure by a cent, which is the T239 defect moved into the
 * browser (FR-048, SC-008, Constitution III).
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'GBP', symbol: '£' } }),
}))

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { children: ReactNode }) => <a>{children}</a>,
}))

vi.mock('@/lib/api/models', () => ({
  listModels: vi.fn(async () => ({ models: [], total: 0 })),
}))

vi.mock('@/lib/api/products', () => ({
  addProductModel: vi.fn(),
  removeProductModel: vi.fn(),
  updateProductModel: vi.fn(),
  addProductComponent: vi.fn(),
  removeProductComponent: vi.fn(),
  updateProductComponent: vi.fn(),
  listProducts: vi.fn(async () => ({ products: [], total: 0 })),
}))

import { ProductModelsEditor } from './ProductModelsEditor'
import { ProductComponentsEditor } from './ProductComponentsEditor'

function renderWithQuery(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

// Three units at a served 1.001 re-sum to 3.003, which shows as £3.00. The
// engine's unrounded subtotal here is 3.0050, which shows as £3.01.
const MODEL = {
  id: 'pm-1',
  product_id: 'product-1',
  model_id: 'model-1',
  quantity: 3,
  model_name: 'Dragon',
  model_sku: 'DRG',
  model_cost: '1.001',
  created_at: '2026-10-25T00:00:00Z',
}

const COMPONENT = {
  id: 'pc-1',
  parent_product_id: 'product-1',
  child_product_id: 'product-2',
  quantity: 3,
  child_product_name: 'Stand',
  child_product_sku: 'STD',
  child_product_cost: '1.001',
  created_at: '2026-10-25T00:00:00Z',
}

function subtotal(label: string): string {
  return screen.getByText(label).textContent ?? ''
}

describe('ProductModelsEditor subtotal', () => {
  it("shows the engine's models cost where a re-sum of the lines would disagree", () => {
    renderWithQuery(
      <ProductModelsEditor productId="product-1" models={[MODEL]} totalCost="3.0050" />,
    )
    expect(subtotal('Total models cost:')).toContain('£3.01')
  })

  it('shows a dash rather than a computed figure when the engine served none', () => {
    renderWithQuery(<ProductModelsEditor productId="product-1" models={[MODEL]} />)
    expect(subtotal('Total models cost:')).toContain('—')
    expect(subtotal('Total models cost:')).not.toContain('£3.00')
  })
})

describe('ProductComponentsEditor subtotal', () => {
  it("shows the engine's child products cost", () => {
    renderWithQuery(
      <ProductComponentsEditor
        productId="product-1"
        components={[COMPONENT]}
        totalCost="3.0050"
      />,
    )
    expect(subtotal('Total child products cost:')).toContain('£3.01')
  })
})
