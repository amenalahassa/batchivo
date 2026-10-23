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

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

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

// The pricing editor reads the role to decide whether a solved price may be
// applied (FR-007a). Stubbed for the same reason as `useCurrency` above: the
// session is not what is under test.
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { email: 'operator@example.com', role: 'admin' },
    logout: vi.fn(),
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
  makeCostOf,
  normaliseMoney,
  sameMakeCost,
} from '@/lib/pricing/makeCost'
import type { ProductPricing } from '@/lib/api/products'
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
  it('is gone, because a float accessor to a cost had no reader left', async () => {
    // Its two callers were the invented suggested prices (task T140) and the
    // float averages (task T143). Keeping it would leave the obvious thing to
    // reach for the next time a screen wants to multiply a cost.
    const module = await import('@/lib/pricing/makeCost')
    expect('makeCostNumber' in module).toBe(false)
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

// ---------------------------------------------------------------------------
// The averages across channels (task T143)
// ---------------------------------------------------------------------------

/** A current, active base-tier price with the engine's own profit and margin. */
function pricingRow(overrides: Partial<ProductPricing> = {}): ProductPricing {
  return {
    id: `pricing-${Math.random().toString(36).slice(2)}`,
    product_id: 'prod-1',
    sales_channel_id: 'channel-1',
    channel_name: 'Etsy',
    platform_type: 'etsy',
    list_price: '30.00',
    is_active: true,
    min_quantity: 1,
    valid_from: '2026-01-01',
    valid_to: null,
    profit: '0.10',
    margin_percentage: '35.0000',
    ...overrides,
  } as ProductPricing
}

describe('ProductPricingEditor averages', () => {
  it('averages the profit the engine sent, exactly', async () => {
    // 0.10 + 0.20 + 0.30 over three channels is 0.20 to the cent. Summed as
    // floats it is 0.6000000000000001, and the mean 0.20000000000000004 --
    // which is the same figure only until something rounds it (Constitution IV).
    renderWithQueryClient(
      <ProductPricingEditor
        productId="prod-1"
        makeCost="20.30"
        pricing={[
          pricingRow({ sales_channel_id: 'c1', channel_name: 'A', profit: '0.10' }),
          pricingRow({ sales_channel_id: 'c2', channel_name: 'B', profit: '0.20' }),
          pricingRow({ sales_channel_id: 'c3', channel_name: 'C', profit: '0.30' }),
        ]}
      />,
    )

    // Scoped to the summary line: a channel row happens to show the same
    // figure, and asserting globally would pass on the wrong element.
    expect(await screen.findByText(/Avg Profit:/)).toHaveTextContent('£0.20')
  })

  it('averages the margin to one place, from the four the API sends', async () => {
    renderWithQueryClient(
      <ProductPricingEditor
        productId="prod-1"
        makeCost="20.30"
        pricing={[
          pricingRow({ sales_channel_id: 'c1', channel_name: 'A', margin_percentage: '35.2693' }),
          pricingRow({ sales_channel_id: 'c2', channel_name: 'B', margin_percentage: '40.0000' }),
        ]}
      />,
    )

    expect(await screen.findByText(/Avg Margin:/)).toHaveTextContent('37.6%')
  })

  it('counts a channel once however many quantity tiers it has', async () => {
    // The 10+ tier must not drag the average: it is the same channel.
    renderWithQueryClient(
      <ProductPricingEditor
        productId="prod-1"
        makeCost="20.30"
        pricing={[
          pricingRow({ sales_channel_id: 'c1', channel_name: 'A', profit: '1.00' }),
          pricingRow({
            sales_channel_id: 'c1',
            channel_name: 'A',
            min_quantity: 10,
            profit: '9.00',
          }),
        ]}
      />,
    )

    expect(await screen.findByText(/Avg Profit:/)).toHaveTextContent('£1.00')
  })

  it('shows no average at all when no channel has a current active price', async () => {
    renderWithQueryClient(
      <ProductPricingEditor productId="prod-1" makeCost="20.30" pricing={[]} />,
    )

    expect(await screen.findByText(/Make Cost:/)).toBeInTheDocument()
    expect(screen.queryByText(/Avg Profit:/)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// No second pricing implementation, and no float money, on these screens
// (tasks T140, T143)
// ---------------------------------------------------------------------------

/**
 * These read the source rather than the rendered output, deliberately.
 *
 * What they guard against is not a wrong number on screen today -- it is a
 * markup or a `parseFloat` being added back tomorrow. A render test can only
 * catch the figures it happens to assert on; reading the source catches the
 * construct, which is what the Constitution actually forbids. The backend
 * holds its money paths the same way, in
 * `backend/tests/unit/pricing/test_no_float_in_money_paths.py`.
 */
const PRODUCT_SCREENS = [
  'ProductDetail.tsx',
  'ProductPricingEditor.tsx',
  'ProductComponentsEditor.tsx',
  'ProductModelsEditor.tsx',
]

function sourceOf(name: string): string {
  return readFileSync(join(__dirname, name), 'utf8')
}

describe('the product screens derive no price of their own', () => {
  it('has no markup multiplier left on the detail page', () => {
    // `totalMakeCost * 2.5`, `/ 0.60` and `* 3.0` were rendered as
    // "Recommended", "Alternative" and "Premium" prices, from markups no
    // operator configured and before any fee, reserve or tax. FR-007 is
    // explicit that what a customer will pay is not the system's to compute.
    const source = sourceOf('ProductDetail.tsx')
    for (const markup of ['* 2.5', '/ 0.60', '* 3.0', '* 3.00']) {
      expect(source).not.toContain(`totalMakeCost ${markup}`)
    }
    expect(source).not.toMatch(/Recommended Price|Premium Price|Alternative Price/)
  })

  it('points the operator at the solver and the ladder instead', () => {
    // Removing the tiles must not leave the screen silent about how a price is
    // actually arrived at (FR-032, FR-007).
    const source = sourceOf('ProductDetail.tsx')
    expect(source).toContain('Find a price')
  })

  it('does not parse a money figure into a float on any of them', () => {
    for (const name of PRODUCT_SCREENS) {
      const offenders = sourceOf(name)
        .split('\n')
        .map((line, index) => [index + 1, line] as const)
        .filter(([, line]) => /parseFloat\s*\(/.test(line))
        .filter(([, line]) => /cost|price|profit|margin|fee|total|revenue/i.test(line))

      expect(
        offenders.map(([lineNumber, line]) => `${name}:${lineNumber}: ${line.trim()}`),
        `${name} turns a money figure into a float; the API sends decimal ` +
          `strings and @/lib/money has exact add, multiply and divide ` +
          `(Constitution IV)`,
      ).toEqual([])
    }
  })

  it('is reading the real files, so these cannot pass vacuously', () => {
    for (const name of PRODUCT_SCREENS) {
      expect(sourceOf(name).length).toBeGreaterThan(1000)
    }
    // A control: the construct being banned is one the checker can see.
    expect(/parseFloat\s*\(/.test('const x = parseFloat(y)')).toBe(true)
  })
})
