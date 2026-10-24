/**
 * Tests for ProductPricingEditor — price history and quantity tiers (T100a)
 *
 * Three things this screen has to get right, because each has a wrong answer
 * that looks plausible:
 *
 * 1. **Only current prices are listed.** A superseded price shown alongside
 *    current ones reads as what the product sells for, and an operator would
 *    price against it.
 * 2. **A quantity tier's bound is unambiguous.** "10+" means ten or more. If
 *    the screen left that to inference, the price of a ten-unit order would be
 *    a coin toss.
 * 3. **The history shows no margin.** Valuing a past price against today's
 *    cost is the restatement FR-038 exists to prevent, and the history dialog
 *    is the most natural place for that mistake to reappear — so there is a
 *    test here whose only job is to fail if a margin column is ever added.
 *
 * Also covered: that a price change is described as opening a new period
 * rather than overwriting one, and that removing a price is described as
 * closing a period, since an operator who believes "remove" deletes the record
 * will not trust the history that follows.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ProductPricingEditor } from './ProductPricingEditor'
import * as productsApi from '@/lib/api/products'
import type { TenantRole } from '@/lib/auth'

vi.mock('@/lib/api/products', () => ({
  addProductPricing: vi.fn(),
  updateProductPricing: vi.fn(),
  removeProductPricing: vi.fn(),
  getProductPricingHistory: vi.fn(),
}))

vi.mock('@/lib/api/sales-channels', () => ({
  listSalesChannels: vi.fn(),
}))

// The price finder has its own tests. Here it is stubbed so this file can
// assert what the editor *hands* it: whether a solved price may be applied is
// the editor's decision, and it is the one FR-007a governs.
const finderProps: { onApply?: (price: string) => void; open?: boolean }[] = []

vi.mock('@/components/pricing/PriceFinderDialog', () => ({
  PriceFinderDialog: (props: { onApply?: (price: string) => void; open?: boolean }) => {
    finderProps.push(props)
    return null
  },
}))

// The breakdown fetches on its own; what matters here is that a row opens it
// for its own channel (T244).
const breakdownProps: { productId: string; channelId: string }[] = []

vi.mock('@/components/pricing/ProductMarginBreakdown', () => ({
  ProductMarginBreakdown: (props: { productId: string; channelId: string }) => {
    breakdownProps.push(props)
    return <div data-testid="margin-breakdown-open">{props.channelId}</div>
  },
}))

vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({
    // The whole hook's shape, not only the formatter: the price finder is
    // handed the symbol on its own, and a mock missing it fails every test in
    // this file for a reason that has nothing to do with pricing.
    currency: { code: 'CAD', symbol: 'CA$' },
    formatCurrency: (value: string | number) => `CA$${Number(value).toFixed(2)}`,
  }),
}))

// The role the mocked `useAuth` reports. The editor reads it to decide whether
// a solved price may be applied to the price itself, which is monetary policy
// (FR-007a). Mocked rather than wrapped in a real `AuthProvider`, which would
// reach for a token: the screen under test is the pricing editor, not the
// session.
let currentRole: TenantRole | null = 'admin'

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { email: 'operator@example.com', role: currentRole },
    logout: vi.fn(),
  }),
}))

import { listSalesChannels } from '@/lib/api/sales-channels'

const PRODUCT_ID = 'prod-1'
const ETSY = '11111111-1111-4111-8111-111111111111'
const SHOPIFY = '22222222-2222-4222-8222-222222222222'

/** One price row, with every field the component reads set explicitly. */
function priceRow(overrides: Partial<productsApi.ProductPricing> = {}): productsApi.ProductPricing {
  return {
    id: `price-${Math.random().toString(36).slice(2)}`,
    product_id: PRODUCT_ID,
    sales_channel_id: ETSY,
    list_price: '64.99',
    is_active: true,
    valid_from: '2026-07-01',
    valid_to: null,
    is_current: true,
    min_quantity: 1,
    channel_name: 'Golden Marketplace',
    platform_type: 'etsy',
    platform_fee: '10.64',
    net_revenue: '54.35',
    profit: '22.92',
    margin_percentage: '35.3',
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
    ...overrides,
  }
}

/**
 * Pick an option from a shadcn (Radix) Select.
 *
 * Radix ignores a pointerup on an item the pointer never moved onto, which is
 * a guard against selecting by accident on open -- so the hover is required,
 * not decoration. Radix also leaves `document.body` at
 * `pointer-events: none` after the listbox closes in jsdom, which blocks every
 * later click, so it is cleared here rather than in each test.
 */
async function chooseOption(
  user: ReturnType<typeof userEvent.setup>,
  name: RegExp
): Promise<void> {
  await user.click(await screen.findByRole('combobox'))
  const option = await screen.findByRole('option', { name })
  await user.hover(option)
  await user.click(option)
  document.body.style.pointerEvents = ''
}

function renderEditor(pricing: productsApi.ProductPricing[], makeCost = '20.30') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ProductPricingEditor productId={PRODUCT_ID} pricing={pricing} makeCost={makeCost} />
      </QueryClientProvider>
    ),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  currentRole = 'admin'
  finderProps.length = 0
  vi.mocked(listSalesChannels).mockResolvedValue({
    channels: [
      { id: ETSY, name: 'Golden Marketplace', platform_type: 'etsy' },
      { id: SHOPIFY, name: 'Own Shop', platform_type: 'shopify' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ] as any,
    total: 2,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any)
  vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue([])
})

// ---------------------------------------------------------------------------
// Quantity tiers
// ---------------------------------------------------------------------------

describe('quantity tiers', () => {
  const tiers = [
    priceRow({ id: 'tier-1', list_price: '64.99', min_quantity: 1 }),
    priceRow({ id: 'tier-10', list_price: '59.99', min_quantity: 10 }),
    priceRow({ id: 'tier-50', list_price: '54.99', min_quantity: 50 }),
  ]

  it('lists every tier on a channel rather than only one price', async () => {
    renderEditor(tiers)

    expect(await screen.findByText('CA$64.99')).toBeInTheDocument()
    expect(screen.getByText('CA$59.99')).toBeInTheDocument()
    expect(screen.getByText('CA$54.99')).toBeInTheDocument()
  })

  it('labels each tier by the quantity it applies from', async () => {
    renderEditor(tiers)

    expect(await screen.findByText('1+')).toBeInTheDocument()
    expect(screen.getByText('10+')).toBeInTheDocument()
    expect(screen.getByText('50+')).toBeInTheDocument()
  })

  it('shows the base tier as "1+" rather than leaving it blank', async () => {
    // A blank would read as "no tier", and every price has one.
    renderEditor([priceRow({ min_quantity: 1 })])

    expect(await screen.findByText('1+')).toBeInTheDocument()
  })

  it('orders a channel\'s tiers by ascending quantity, not by insertion', async () => {
    renderEditor([
      priceRow({ id: 'b', list_price: '54.99', min_quantity: 50 }),
      priceRow({ id: 'a', list_price: '64.99', min_quantity: 1 }),
      priceRow({ id: 'c', list_price: '59.99', min_quantity: 10 }),
    ])

    const cells = await screen.findAllByText(/^\d+\+$/)
    expect(cells.map((cell) => cell.textContent)).toEqual(['1+', '10+', '50+'])
  })

  it('groups tiers by channel', async () => {
    renderEditor([
      priceRow({ id: 's1', sales_channel_id: SHOPIFY, channel_name: 'Own Shop', min_quantity: 10 }),
      priceRow({ id: 'e1', min_quantity: 10 }),
      priceRow({ id: 'e2', min_quantity: 1 }),
      priceRow({ id: 's2', sales_channel_id: SHOPIFY, channel_name: 'Own Shop', min_quantity: 1 }),
    ])

    const rows = await screen.findAllByRole('row')
    const channels = rows
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[0]?.textContent ?? '')
    expect(channels[0]).toContain('Golden Marketplace')
    expect(channels[1]).toContain('Golden Marketplace')
    expect(channels[2]).toContain('Own Shop')
    expect(channels[3]).toContain('Own Shop')
  })

  it('says plainly that a tier means that quantity or more', async () => {
    // The ambiguity this removes is worth money: whether a ten-unit order gets
    // the "10+" price depends on it.
    const user = userEvent.setup({ delay: null })
    renderEditor([])

    await user.click(screen.getByRole('button', { name: /add pricing/i }))

    expect(await screen.findByText(/or more/i)).toBeInTheDocument()
  })

  it('sends the tier when adding a price', async () => {
    vi.mocked(productsApi.addProductPricing).mockResolvedValue(priceRow())
    const user = userEvent.setup({ delay: null })
    renderEditor([])

    await user.click(screen.getByRole('button', { name: /add pricing/i }))
    await chooseOption(user, /Own Shop/)
    await user.type(screen.getByPlaceholderText('19.99'), '59.99')

    const tierField = screen.getByLabelText(/applies from quantity/i)
    await user.clear(tierField)
    await user.type(tierField, '10')

    await user.click(screen.getByRole('button', { name: /^add pricing$/i }))

    await waitFor(() => {
      expect(productsApi.addProductPricing).toHaveBeenCalledWith(
        PRODUCT_ID,
        expect.objectContaining({ min_quantity: 10, list_price: '59.99' })
      )
    })
  })

  it('defaults a new price to the base tier', async () => {
    vi.mocked(productsApi.addProductPricing).mockResolvedValue(priceRow())
    const user = userEvent.setup({ delay: null })
    renderEditor([])

    await user.click(screen.getByRole('button', { name: /add pricing/i }))
    await chooseOption(user, /Own Shop/)
    await user.type(screen.getByPlaceholderText('19.99'), '64.99')
    await user.click(screen.getByRole('button', { name: /^add pricing$/i }))

    await waitFor(() => {
      expect(productsApi.addProductPricing).toHaveBeenCalledWith(
        PRODUCT_ID,
        expect.objectContaining({ min_quantity: 1 })
      )
    })
  })

  it('will not let an existing tier be moved to another quantity', async () => {
    // The tier is part of the row's identity. Editing it in place would make
    // two tiers collide, which the API refuses; the field is disabled instead
    // so the operator adds a tier rather than discovering a 409.
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow({ min_quantity: 10 })])

    await user.click(await screen.findByRole('button', { name: /edit price for/i }))

    const tierField = await screen.findByLabelText(/applies from quantity/i)
    expect(tierField).toHaveAttribute('readonly')
    expect(tierField).toHaveAttribute('aria-disabled', 'true')
    // Read-only rather than disabled on purpose: react-hook-form reads a
    // disabled input as undefined, which would fail this field's validation
    // and silently block the whole edit from submitting.
    expect(tierField).toHaveValue(10)
  })

  it('averages over the base tier only', async () => {
    // Counting a channel's 1+, 10+ and 50+ prices as three channels would drag
    // the average toward whichever channel has the most tiers.
    renderEditor([
      priceRow({ id: 'a', min_quantity: 1, profit: '22.92', margin_percentage: '35.3' }),
      priceRow({ id: 'b', min_quantity: 10, profit: '2.00', margin_percentage: '3.0' }),
      priceRow({ id: 'c', min_quantity: 50, profit: '1.00', margin_percentage: '1.0' }),
    ])

    // Asserted on the summary line specifically. The discounted rows show
    // their own low margins, which is correct -- what must not happen is the
    // average being dragged down to the mean of all three (13.1%).
    const summary = (await screen.findByText(/Avg Margin/)).parentElement
    expect(summary?.textContent).toContain('35.3%')
    expect(summary?.textContent).not.toContain('13.1%')

    const profit = screen.getByText(/Avg Profit/).parentElement
    expect(profit?.textContent).toContain('CA$22.92')
  })

  it('keeps every channel selectable, since a channel can carry several tiers', async () => {
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow({ min_quantity: 1 })])

    await user.click(screen.getByRole('button', { name: /add pricing/i }))
    await user.click(await screen.findByRole('combobox'))

    // The channel already priced at 1+ must still be offered, so a 10+ tier
    // can be added to it.
    expect(await screen.findByRole('option', { name: /Golden Marketplace/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Own Shop/ })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Effective periods
// ---------------------------------------------------------------------------

describe('effective periods', () => {
  it('shows the period a current price has applied for', async () => {
    renderEditor([priceRow({ valid_from: '2026-07-01', valid_to: null })])

    expect(await screen.findByText(/^Since /)).toBeInTheDocument()
  })

  it('names the open end rather than leaving the column blank', async () => {
    // A blank end date reads as missing data; "Since ..." reads as current.
    renderEditor([priceRow({ valid_to: null })])

    const period = await screen.findByText(/^Since /)
    expect(period.textContent).toMatch(/Since \w+/)
  })

  it('does not list a superseded price as a current one', async () => {
    renderEditor([
      priceRow({ id: 'old', list_price: '49.99', valid_to: '2026-06-30', is_current: false }),
      priceRow({ id: 'now', list_price: '64.99', valid_to: null }),
    ])

    expect(await screen.findByText('CA$64.99')).toBeInTheDocument()
    expect(screen.queryByText('CA$49.99')).not.toBeInTheDocument()
  })

  it('reports no pricing when every period has been closed', async () => {
    renderEditor([priceRow({ valid_to: '2026-06-30', is_current: false })])

    expect(await screen.findByText(/No pricing set yet/i)).toBeInTheDocument()
  })

  it('says that changing a price opens a new period', async () => {
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /edit price for/i }))

    expect(await screen.findByText(/opens a new period/i)).toBeInTheDocument()
  })

  it('does not prefill the old period start when editing', async () => {
    // Reusing the current period's start date overlaps it, which the API
    // refuses. Blank means today, which is what a price change means.
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow({ valid_from: '2026-07-01' })])

    await user.click(await screen.findByRole('button', { name: /edit price for/i }))

    expect(await screen.findByLabelText(/applies from date/i)).toHaveValue('')
  })

  it('omits the date entirely when left blank, rather than sending an empty string', async () => {
    vi.mocked(productsApi.updateProductPricing).mockResolvedValue(priceRow())
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow({ id: 'p1' })])

    await user.click(await screen.findByRole('button', { name: /edit price for/i }))
    const priceField = await screen.findByPlaceholderText('19.99')
    await user.clear(priceField)
    await user.type(priceField, '69.99')
    await user.click(screen.getByRole('button', { name: /^update$/i }))

    await waitFor(() => {
      expect(productsApi.updateProductPricing).toHaveBeenCalled()
    })
    const [, , payload] = vi.mocked(productsApi.updateProductPricing).mock.calls[0]
    expect(payload).not.toHaveProperty('valid_from')
    expect(payload.list_price).toBe('69.99')
  })

  it('sends a backdated start when one is given', async () => {
    vi.mocked(productsApi.addProductPricing).mockResolvedValue(priceRow())
    const user = userEvent.setup({ delay: null })
    renderEditor([])

    await user.click(screen.getByRole('button', { name: /add pricing/i }))
    await chooseOption(user, /Own Shop/)
    await user.type(screen.getByPlaceholderText('19.99'), '64.99')
    await user.type(screen.getByLabelText(/applies from date/i), '2026-01-15')
    await user.click(screen.getByRole('button', { name: /^add pricing$/i }))

    await waitFor(() => {
      expect(productsApi.addProductPricing).toHaveBeenCalledWith(
        PRODUCT_ID,
        expect.objectContaining({ valid_from: '2026-01-15' })
      )
    })
  })
})

// ---------------------------------------------------------------------------
// The history dialog
// ---------------------------------------------------------------------------

describe('price history', () => {
  const history: productsApi.ProductPricing[] = [
    {
      ...priceRow({ id: 'h3', list_price: '64.99', valid_from: '2026-08-01', valid_to: null }),
      platform_fee: undefined,
      net_revenue: undefined,
      profit: undefined,
      margin_percentage: undefined,
    },
    {
      ...priceRow({
        id: 'h2',
        list_price: '59.99',
        valid_from: '2026-07-01',
        valid_to: '2026-07-31',
        is_current: false,
      }),
      platform_fee: undefined,
      net_revenue: undefined,
      profit: undefined,
      margin_percentage: undefined,
    },
    {
      ...priceRow({
        id: 'h1',
        list_price: '49.99',
        valid_from: '2026-01-01',
        valid_to: '2026-06-30',
        is_current: false,
      }),
      platform_fee: undefined,
      net_revenue: undefined,
      profit: undefined,
      margin_percentage: undefined,
    },
  ]

  it('is not fetched until it is opened', async () => {
    // A history grows without bound and most visits never open it.
    renderEditor([priceRow()])

    await screen.findByText('CA$64.99')
    expect(productsApi.getProductPricingHistory).not.toHaveBeenCalled()
  })

  it('fetches the history for the channel whose button was clicked', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue(history)
    const user = userEvent.setup({ delay: null })
    renderEditor([
      priceRow({ id: 'e', sales_channel_id: ETSY }),
      priceRow({ id: 's', sales_channel_id: SHOPIFY, channel_name: 'Own Shop' }),
    ])

    await user.click(await screen.findByRole('button', { name: /price history for Own Shop/i }))

    await waitFor(() => {
      expect(productsApi.getProductPricingHistory).toHaveBeenCalledWith(PRODUCT_ID, SHOPIFY)
    })
  })

  it('shows every past price, not only the current one', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue(history)
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))

    expect(await screen.findByText('CA$59.99')).toBeInTheDocument()
    expect(screen.getByText('CA$49.99')).toBeInTheDocument()
  })

  it('marks which period is current and which are superseded', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue(history)
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))

    expect(await screen.findByText('Current')).toBeInTheDocument()
    expect(screen.getAllByText('Superseded')).toHaveLength(2)
  })

  it('shows a closed period with both its ends', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue(history)
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))

    // A closed period reads as two dates joined by a dash, as opposed to the
    // open-ended "Since ...". Asserted on shape rather than on one locale's
    // output, which varies with the runner's ICU data.
    const dialog = await screen.findByRole('dialog')
    const closed = within(dialog)
      .getAllByRole('row')
      // `queryAllByRole`, because the header row has columnheaders and no
      // cells, and `getAllByRole` throws on an empty match.
      .map((row) => within(row).queryAllByRole('cell')[0]?.textContent ?? '')
      .filter((text) => / - /.test(text))
    expect(closed).toHaveLength(2)
    expect(closed[0]).toMatch(/2026.* - .*2026/)
  })

  it('shows no margin or profit column against a past price', async () => {
    // The single most important assertion in this file. A margin here would be
    // a past price valued against today's cost, which is the restatement
    // FR-038 exists to prevent -- and it would look entirely reasonable.
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue(history)
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))
    const dialog = await screen.findByRole('dialog')

    const headers = within(dialog)
      .getAllByRole('columnheader')
      .map((header) => header.textContent?.toLowerCase() ?? '')
    expect(headers).not.toContain('margin')
    expect(headers).not.toContain('profit')
    expect(headers.some((header) => header.includes('margin'))).toBe(false)
    expect(headers.some((header) => header.includes('profit'))).toBe(false)
  })

  it('explains why there is no margin, rather than leaving it unexplained', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue(history)
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))

    expect(await screen.findByText(/restate history/i)).toBeInTheDocument()
  })

  it('reports an empty history plainly', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue([])
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))

    expect(await screen.findByText(/No price history/i)).toBeInTheDocument()
  })

  it('shows the tier each historical price applied to', async () => {
    vi.mocked(productsApi.getProductPricingHistory).mockResolvedValue([
      priceRow({ id: 'h', min_quantity: 25, valid_to: '2026-06-30', is_current: false }),
    ])
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /price history for/i }))
    const dialog = await screen.findByRole('dialog')

    expect(within(dialog).getByText('25+')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Closing a period
// ---------------------------------------------------------------------------

describe('closing a period', () => {
  it('describes removal as closing a period, not deleting a record', async () => {
    // An operator who believes "remove" deletes the record will not trust the
    // history that follows it.
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /stop selling at/i }))

    expect(await screen.findByText(/stays in the history/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /close period/i })).toBeInTheDocument()
  })

  it('says that orders already placed keep their price', async () => {
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])

    await user.click(await screen.findByRole('button', { name: /stop selling at/i }))

    expect(await screen.findByText(/what they were charged/i)).toBeInTheDocument()
  })

  it('names the tier it is about to close', async () => {
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow({ min_quantity: 10 })])

    await user.click(await screen.findByRole('button', { name: /stop selling at 10\+/i }))

    const dialog = await screen.findByRole('alertdialog')
    expect(dialog.textContent).toContain('10+')
  })

  it('closes the period through the API', async () => {
    vi.mocked(productsApi.removeProductPricing).mockResolvedValue(undefined)
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow({ id: 'to-close' })])

    await user.click(await screen.findByRole('button', { name: /stop selling at/i }))
    await user.click(await screen.findByRole('button', { name: /close period/i }))

    await waitFor(() => {
      expect(productsApi.removeProductPricing).toHaveBeenCalledWith(PRODUCT_ID, 'to-close')
    })
  })
})

// ---------------------------------------------------------------------------
// What the screen still has to do
// ---------------------------------------------------------------------------

describe('the figures already on this screen', () => {
  it('still shows the make-cost as the exact string the API sent', async () => {
    renderEditor([priceRow()], '20.30')

    expect(await screen.findByText('CA$20.30')).toBeInTheDocument()
  })

  it('still names the basis beside the margin', async () => {
    // FR-031b: the same sale reads differently on the other two bases, so the
    // percentage is meaningless without it.
    renderEditor([priceRow()])

    expect((await screen.findAllByText('35.3%')).length).toBeGreaterThan(0)
    expect(screen.getByText(/customer total/i)).toBeInTheDocument()
  })

  it('invalidates the history after a price change, so it is not stale', async () => {
    vi.mocked(productsApi.updateProductPricing).mockResolvedValue(priceRow())
    const user = userEvent.setup({ delay: null })
    const { queryClient } = renderEditor([priceRow({ id: 'p1' })])
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(await screen.findByRole('button', { name: /edit price for/i }))
    const priceField = await screen.findByPlaceholderText('19.99')
    await user.clear(priceField)
    await user.type(priceField, '69.99')
    await user.click(screen.getByRole('button', { name: /^update$/i }))

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ['product-pricing-history', PRODUCT_ID],
      })
    })
  })
})

describe('who may apply a solved price (FR-007a)', () => {
  /** Open the finder on the one priced channel, and report its props. */
  async function openFinder() {
    const user = userEvent.setup({ delay: null })
    renderEditor([priceRow()])
    await user.click(await screen.findByRole('button', { name: /find a price for/i }))
    return finderProps[finderProps.length - 1]
  }

  it('offers an admin a way to take the price', async () => {
    expect(typeof (await openFinder())?.onApply).toBe('function')
  })

  it('offers an owner the same', async () => {
    currentRole = 'owner'

    expect(typeof (await openFinder())?.onApply).toBe('function')
  })

  it('leaves the finder read-only for a viewer', async () => {
    // Reading the ladder is open to every role (FR-007c); taking the price is
    // a write. A control that looks enabled and then fails on save is worse
    // than one plainly not offered (FR-007d).
    currentRole = 'viewer'

    const props = await openFinder()

    expect(props?.open).toBe(true)
    expect(props?.onApply).toBeUndefined()
  })

  it('leaves it read-only for a member, whose remit is operational', async () => {
    // FR-007b: a member sets print time and waste, not what a thing sells for.
    currentRole = 'member'

    expect((await openFinder())?.onApply).toBeUndefined()
  })

  it('leaves it read-only when no role is known at all', async () => {
    // A missing role is read-only, never permissive: a session that has not
    // reported one must not be assumed to be an admin.
    currentRole = null

    expect((await openFinder())?.onApply).toBeUndefined()
  })
})

describe('profit per machine-hour beside the margin (T234, FR-043)', () => {
  it('shows what each price pays per hour of the machine', async () => {
    renderEditor([priceRow({ id: 'timed', profit_per_machine_hour: '9.17' })])

    expect(await screen.findByTestId('profit-per-machine-hour-timed')).toHaveTextContent(
      'CA$9.17/machine-hr',
    )
  })

  it('says untimed, never zero, where nobody has timed the print', async () => {
    renderEditor([priceRow({ id: 'untimed', profit_per_machine_hour: null })])

    expect(await screen.findByTestId('profit-per-machine-hour-untimed')).toHaveTextContent(
      'untimed',
    )
  })
})

describe('margin breakdown (T244)', () => {
  it('opens the full margin for the channel of its own row', async () => {
    renderEditor([priceRow()])
    const button = await screen.findByRole('button', {
      name: 'Margin breakdown for Golden Marketplace',
    })
    await userEvent.click(button)

    expect(await screen.findByTestId('margin-breakdown-open')).toBeInTheDocument()
    expect(breakdownProps.at(-1)).toEqual({
      productId: expect.any(String),
      channelId: priceRow().sales_channel_id,
    })
  })
})
