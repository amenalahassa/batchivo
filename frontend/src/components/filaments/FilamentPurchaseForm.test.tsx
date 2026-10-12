/**
 * FilamentPurchaseForm tests.
 *
 * The allocation is the reason this screen exists, so most of what is asserted
 * here is about it: each spool's share of the shipping, the usable weight
 * rather than the nominal one, the derivation behind the per-gram figure, and
 * the fallbacks named in words when a weight is missing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { FilamentPurchaseForm, SpoolAllocationTable } from './FilamentPurchaseForm'
import { pricingApi } from '@/lib/api/pricing'
import type { FilamentPurchase, SpoolLandedCost } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getFilamentPurchase: vi.fn(),
    createFilamentPurchase: vi.fn(),
    updateFilamentPurchase: vi.fn(),
    deleteFilamentPurchase: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)
const PURCHASE_ID = 'purchase-1'

/** The golden case's filament: CA$31.00 landed per 1000 g, 25 g unusable. */
function spool(overrides: Partial<SpoolLandedCost> = {}): SpoolLandedCost {
  return {
    spool_id: 'spool-1',
    spool_label: 'PLA-BLACK-001',
    purchase_price: '25.00',
    allocated_shipping: '4.50',
    allocated_tax: '1.50',
    tax_recoverable: false,
    nominal_weight_grams: '1000',
    unusable_remainder_grams: '25',
    usable_weight_grams: '975',
    total_landed_cost: '31.00',
    cost_per_gram: '0.0317948717948718',
    even_split_fallback: false,
    incomplete_reasons: [],
    derivation: [
      'purchase price 25.00',
      'purchase abc: shipping 18.00 allocated by weight to 4.50',
      'usable weight 1000 - 25 = 975 g (FR-008d: never nominal)',
    ],
    ...overrides,
  }
}

function purchase(overrides: Partial<FilamentPurchase> = {}): FilamentPurchase {
  return {
    id: PURCHASE_ID,
    supplier: 'Polymaker',
    purchase_date: '2026-03-01',
    inbound_shipping_cost: '18.00',
    tax_amount: '6.00',
    tax_recoverable: false,
    order_reference: 'PO-4471',
    notes: null,
    spools: [spool()],
    allocation_notes: [],
    ...overrides,
  }
}

function renderForm(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('SpoolAllocationTable', () => {
  it('shows each spool’s share of the shipping', () => {
    render(<SpoolAllocationTable spools={[spool()]} />)

    const row = within(screen.getByTestId('spool-allocation-spool-1'))
    expect(row.getByText('$4.50')).toBeInTheDocument()
  })

  it('shows the landed cost and the per-usable-gram figure', () => {
    render(<SpoolAllocationTable spools={[spool()]} />)

    const row = within(screen.getByTestId('spool-allocation-spool-1'))
    expect(row.getByText('$31.00')).toBeInTheDocument()
    expect(row.getByText(/\$0.03 per usable gram/)).toBeInTheDocument()
  })

  it('shows the usable weight, not the nominal weight', () => {
    render(<SpoolAllocationTable spools={[spool()]} />)

    // The dd carries both figures, so assert on the definition itself rather
    // than on a text match that the ancestor element also satisfies.
    const row = within(screen.getByTestId('spool-allocation-spool-1'))
    const usable = row.getByText('Usable weight').nextElementSibling
    expect(usable).toHaveTextContent('975 g')
    expect(usable).toHaveTextContent('(25 g unusable)')
  })

  it('says recoverable tax was excluded rather than showing a bare zero', () => {
    render(
      <SpoolAllocationTable
        spools={[spool({ tax_recoverable: true, allocated_tax: '0' })]}
      />,
    )

    const row = within(screen.getByTestId('spool-allocation-spool-1'))
    expect(row.getByText('Tax (recoverable, excluded)')).toBeInTheDocument()
  })

  it('offers the derivation, so the figure can be checked', async () => {
    const user = userEvent.setup()
    render(<SpoolAllocationTable spools={[spool()]} />)

    await user.click(screen.getByText('How this was worked out'))
    expect(
      screen.getByText('usable weight 1000 - 25 = 975 g (FR-008d: never nominal)'),
    ).toBeInTheDocument()
  })

  it('says when shipping fell back to an even split', () => {
    render(<SpoolAllocationTable spools={[spool({ even_split_fallback: true })]} />)

    expect(screen.getByTestId('even-split-spool-1')).toHaveTextContent(
      /split evenly rather than by weight/,
    )
  })

  it('shows no even-split note when shipping went by weight', () => {
    render(<SpoolAllocationTable spools={[spool()]} />)
    expect(screen.queryByTestId('even-split-spool-1')).not.toBeInTheDocument()
  })

  it('reports an unknown per-gram cost as unknown, never as zero', () => {
    render(
      <SpoolAllocationTable
        spools={[
          spool({
            cost_per_gram: null,
            total_landed_cost: null,
            purchase_price: null,
            incomplete_reasons: ['the spool has no purchase price'],
          }),
        ]}
      />,
    )

    const row = within(screen.getByTestId('spool-allocation-spool-1'))
    expect(row.getByText('per-gram cost not yet known')).toBeInTheDocument()
    expect(screen.getByTestId('incomplete-spool-1')).toHaveTextContent(
      'the spool has no purchase price',
    )
  })

  it('allocates differently per spool when the weights differ', () => {
    render(
      <SpoolAllocationTable
        spools={[
          spool({ spool_id: 'small', spool_label: 'SMALL', allocated_shipping: '1.38' }),
          spool({ spool_id: 'large', spool_label: 'LARGE', allocated_shipping: '5.54' }),
        ]}
      />,
    )

    expect(
      within(screen.getByTestId('spool-allocation-small')).getByText('$1.38'),
    ).toBeInTheDocument()
    expect(
      within(screen.getByTestId('spool-allocation-large')).getByText('$5.54'),
    ).toBeInTheDocument()
  })

  it('says so when no spool is attached yet', () => {
    render(<SpoolAllocationTable spools={[]} />)
    expect(screen.getByTestId('no-spools-yet')).toBeInTheDocument()
  })
})

describe('FilamentPurchaseForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getFilamentPurchase.mockResolvedValue(purchase())
    mocked.createFilamentPurchase.mockResolvedValue(purchase())
    mocked.updateFilamentPurchase.mockResolvedValue(purchase())
  })

  it('records a new purchase without loading one first', async () => {
    const user = userEvent.setup()
    renderForm(<FilamentPurchaseForm />)

    expect(mocked.getFilamentPurchase).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('Supplier'), 'Polymaker')
    await user.type(screen.getByLabelText('Purchase date'), '2026-03-01')
    await user.type(screen.getByLabelText('Inbound shipping'), '18.00')
    await user.click(screen.getByRole('button', { name: /Record purchase/ }))

    await waitFor(() => {
      expect(mocked.createFilamentPurchase).toHaveBeenCalled()
    })
    const sent = mocked.createFilamentPurchase.mock.calls[0][0]
    expect(sent.supplier).toBe('Polymaker')
    expect(sent.inbound_shipping_cost).toBe('18.00')
  })

  it('refuses a purchase with no date', async () => {
    const user = userEvent.setup()
    renderForm(<FilamentPurchaseForm />)

    await user.type(screen.getByLabelText('Supplier'), 'Polymaker')
    await user.click(screen.getByRole('button', { name: /Record purchase/ }))

    await waitFor(() => {
      expect(screen.getByText('When did you buy it?')).toBeInTheDocument()
    })
    expect(mocked.createFilamentPurchase).not.toHaveBeenCalled()
  })

  it('refuses negative shipping', async () => {
    const user = userEvent.setup()
    renderForm(<FilamentPurchaseForm />)

    await user.type(screen.getByLabelText('Purchase date'), '2026-03-01')
    await user.type(screen.getByLabelText('Inbound shipping'), '-5')
    await user.click(screen.getByRole('button', { name: /Record purchase/ }))

    await waitFor(() => {
      expect(screen.getByText(/Enter a non-negative amount/)).toBeInTheDocument()
    })
    expect(mocked.createFilamentPurchase).not.toHaveBeenCalled()
  })

  it('loads an existing purchase and shows what each spool landed at', async () => {
    renderForm(<FilamentPurchaseForm purchaseId={PURCHASE_ID} />)

    await waitFor(() => {
      expect(screen.getByLabelText('Supplier')).toHaveValue('Polymaker')
    })
    expect(screen.getByTestId('spool-allocation')).toBeInTheDocument()
    expect(screen.getByText('What each spool landed at')).toBeInTheDocument()
  })

  it('shows the allocation notes the engine supplied', async () => {
    mocked.getFilamentPurchase.mockResolvedValue(
      purchase({
        allocation_notes: ['recoverable sales tax was excluded from landed cost (FR-008c)'],
      }),
    )
    renderForm(<FilamentPurchaseForm purchaseId={PURCHASE_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('allocation-notes')).toHaveTextContent(
        'recoverable sales tax was excluded from landed cost (FR-008c)',
      )
    })
  })

  it('corrects an existing purchase rather than creating another', async () => {
    const user = userEvent.setup()
    renderForm(<FilamentPurchaseForm purchaseId={PURCHASE_ID} />)

    const shipping = await screen.findByLabelText('Inbound shipping')
    await user.clear(shipping)
    await user.type(shipping, '36.00')
    await user.click(screen.getByRole('button', { name: /Save purchase/ }))

    await waitFor(() => {
      expect(mocked.updateFilamentPurchase).toHaveBeenCalled()
    })
    expect(mocked.createFilamentPurchase).not.toHaveBeenCalled()
    const [id, data] = mocked.updateFilamentPurchase.mock.calls[0]
    expect(id).toBe(PURCHASE_ID)
    expect(data.inbound_shipping_cost).toBe('36.00')
  })

  it('reports a failed save instead of appearing to have saved', async () => {
    const user = userEvent.setup()
    mocked.createFilamentPurchase.mockRejectedValue(new Error('Validation failed'))
    renderForm(<FilamentPurchaseForm />)

    await user.type(screen.getByLabelText('Purchase date'), '2026-03-01')
    await user.click(screen.getByRole('button', { name: /Record purchase/ }))

    await waitFor(() => {
      expect(screen.getByText('Validation failed')).toBeInTheDocument()
    })
  })

  it('does not raise the handled failure as an unhandled rejection', async () => {
    // `mutateAsync` rejects, and awaiting it inside react-hook-form's submit
    // handler used to let that rejection escape: the message below appeared
    // *and* the browser reported an unhandled rejection, which would have
    // reached Sentry as an uncaught error on a failure the UI had handled.
    const user = userEvent.setup()
    const unhandled = vi.fn()
    process.on('unhandledRejection', unhandled)
    mocked.createFilamentPurchase.mockRejectedValue(new Error('Validation failed'))

    try {
      const onSaved = vi.fn()
      renderForm(<FilamentPurchaseForm onSaved={onSaved} />)

      await user.type(screen.getByLabelText('Purchase date'), '2026-03-01')
      await user.click(screen.getByRole('button', { name: /Record purchase/ }))

      await waitFor(() => {
        expect(screen.getByText('Validation failed')).toBeInTheDocument()
      })

      // The save did not happen, so nothing downstream may be told it did.
      expect(onSaved).not.toHaveBeenCalled()
      // And the operator's input survives for another attempt.
      expect(screen.getByLabelText('Purchase date')).toHaveValue('2026-03-01')

      await new Promise((resolve) => setTimeout(resolve, 0))
      expect(unhandled).not.toHaveBeenCalled()
    } finally {
      process.off('unhandledRejection', unhandled)
    }
  })

  it('reports a failed load instead of an empty form', async () => {
    mocked.getFilamentPurchase.mockRejectedValue(new Error('boom'))
    renderForm(<FilamentPurchaseForm purchaseId={PURCHASE_ID} />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load this purchase')).toBeInTheDocument()
    })
  })
})
