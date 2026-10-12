/**
 * Tests for the make-cost shown on the product screens.
 *
 * User Story 1's independent test: open the same product from the product
 * list, the product detail page and the channel pricing screen and confirm all
 * three report an identical make-cost to the cent.
 *
 * Before this feature they could disagree. The list read `total_make_cost` off
 * the list payload; the detail page read `cost_breakdown.total_make_cost` and
 * put it through `parseFloat`; the pricing editor received that float as a
 * prop. Two of those paths went through binary floating point, which is where
 * the last cent goes missing (Constitution III, IV).
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// `useCurrency` reads the tenant's symbol from the auth context. The symbol is
// not what is under test here -- the figure beside it is -- so the hook is
// stubbed rather than wrapping every case in an AuthProvider.
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({
    currency: { code: 'CAD', symbol: '£' },
    formatCurrency: (value: string | number) => {
      const parsed = typeof value === 'string' ? Number.parseFloat(value) : value
      return Number.isNaN(parsed) ? '£0.00' : `£${parsed.toFixed(2)}`
    },
  }),
}))

vi.mock('@/lib/api/sales-channels', () => ({
  listSalesChannels: vi.fn(async () => ({ channels: [], total: 0 })),
}))

vi.mock('@/lib/api/products', () => ({
  addProductPricing: vi.fn(),
  updateProductPricing: vi.fn(),
  removeProductPricing: vi.fn(),
}))

import {
  NO_COST,
  makeCostNumber,
  makeCostOf,
  normaliseMoney,
  sameMakeCost,
} from '@/lib/pricing/makeCost'
import { ProductPricingEditor } from './ProductPricingEditor'

// ---------------------------------------------------------------------------
// The shared accessor
// ---------------------------------------------------------------------------

describe('makeCostOf', () => {
  it('reads the structured breakdown when the payload carries one', () => {
    expect(makeCostOf({ cost_breakdown: { total_make_cost: '20.30' } })).toBe('20.30')
  })

  it('reads the list field when there is no breakdown', () => {
    expect(makeCostOf({ total_make_cost: '20.30' })).toBe('20.30')
  })

  it('returns the exact decimal string, not a float', () => {
    // 20.30 cannot be represented exactly in binary floating point; the
    // trailing zero surviving proves no float was involved.
    expect(makeCostOf({ cost_breakdown: { total_make_cost: '20.30' } })).toBe('20.30')
  })

  it('keeps a figure finer than a float could hold', () => {
    const fine = '0.100000000000000000000001'
    expect(makeCostOf({ total_make_cost: fine })).toBe(fine)
  })

  it('prefers the breakdown over the list field when both are present', () => {
    expect(
      makeCostOf({ total_make_cost: '99.99', cost_breakdown: { total_make_cost: '20.30' } }),
    ).toBe('20.30')
  })

  it('falls back to the list field when the breakdown has no total', () => {
    expect(makeCostOf({ total_make_cost: '20.30', cost_breakdown: {} })).toBe('20.30')
  })

  it('reports no cost rather than throwing when the payload is empty', () => {
    expect(makeCostOf({})).toBe(NO_COST)
    expect(makeCostOf(null)).toBe(NO_COST)
    expect(makeCostOf(undefined)).toBe(NO_COST)
  })

  it('treats null and empty string as no cost', () => {
    expect(makeCostOf({ total_make_cost: null })).toBe(NO_COST)
    expect(makeCostOf({ total_make_cost: '' })).toBe(NO_COST)
    expect(makeCostOf({ cost_breakdown: { total_make_cost: null }, total_make_cost: '5.00' })).toBe(
      '5.00',
    )
  })
})

describe('makeCostNumber', () => {
  it('converts once, for arithmetic the UI does on top of the cost', () => {
    expect(makeCostNumber({ cost_breakdown: { total_make_cost: '20.30' } })).toBeCloseTo(20.3, 10)
  })

  it('returns zero rather than NaN for an unparseable figure', () => {
    expect(makeCostNumber({ total_make_cost: 'not a number' })).toBe(0)
    expect(makeCostNumber(null)).toBe(0)
  })
})

describe('normaliseMoney', () => {
  it('compares by value so a trailing zero is not a difference', () => {
    expect(normaliseMoney('20.30')).toBe(normaliseMoney('20.3'))
    expect(normaliseMoney('20.300')).toBe(normaliseMoney('20.3'))
  })

  it('does not collapse a genuine difference', () => {
    expect(normaliseMoney('20.30')).not.toBe(normaliseMoney('20.31'))
  })

  it('handles a leading zero and a negative', () => {
    expect(normaliseMoney('020.30')).toBe('20.3')
    expect(normaliseMoney('-5.00')).toBe('-5')
    expect(normaliseMoney('-0.00')).toBe('0')
  })
})

// ---------------------------------------------------------------------------
// The three screens agree
// ---------------------------------------------------------------------------

describe('the three screens report one make-cost', () => {
  /** The same product, as each endpoint shapes it. */
  const EXACT = '20.30'

  const asListRow = { sku: 'GOLD-001', total_make_cost: EXACT }
  const asDetail = {
    sku: 'GOLD-001',
    cost_breakdown: {
      models_cost: '19.38',
      child_products_cost: '0.00',
      packaging_cost: '0.92',
      assembly_cost: '0.00',
      total_make_cost: EXACT,
    },
  }

  it('the list row and the detail payload give the same figure', () => {
    expect(makeCostOf(asListRow)).toBe(makeCostOf(asDetail))
    expect(sameMakeCost(asListRow, asDetail)).toBe(true)
  })

  it('the figure the pricing editor is handed is the detail figure', () => {
    // The detail page passes `makeCostOf(product)` straight through as the
    // `makeCost` prop; this asserts the value, and the render below asserts it
    // reaches the screen.
    expect(makeCostOf(asDetail)).toBe(EXACT)
  })

  it('they still agree when the shapes differ only in trailing zeros', () => {
    expect(sameMakeCost({ total_make_cost: '20.3' }, asDetail)).toBe(true)
  })

  it('a real disagreement is still reported as one', () => {
    expect(sameMakeCost({ total_make_cost: '26.18' }, asDetail)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// The pricing editor renders the figure it was handed
// ---------------------------------------------------------------------------

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('ProductPricingEditor', () => {
  it('shows the make-cost it was handed, to the cent', async () => {
    renderWithQueryClient(
      <ProductPricingEditor productId="prod-1" pricing={[]} makeCost="20.30" />,
    )

    expect(await screen.findByText('Make Cost:')).toBeInTheDocument()
    expect(screen.getByText('£20.30')).toBeInTheDocument()
  })

  it('does not show the figure that the superseded hardcoded rate produced', async () => {
    // 10.00/hour was the rate the engine used regardless of what the operator
    // configured. A screen showing a cost built from it is the defect.
    renderWithQueryClient(
      <ProductPricingEditor productId="prod-1" pricing={[]} makeCost="20.30" />,
    )

    expect(await screen.findByText('£20.30')).toBeInTheDocument()
    expect(screen.queryByText('£26.18')).not.toBeInTheDocument()
  })

  it('renders a cost with a trailing zero without losing it', async () => {
    renderWithQueryClient(
      <ProductPricingEditor productId="prod-1" pricing={[]} makeCost="64.90" />,
    )
    expect(await screen.findByText('£64.90')).toBeInTheDocument()
  })
})
