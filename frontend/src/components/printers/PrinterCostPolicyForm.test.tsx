/**
 * PrinterCostPolicyForm tests.
 *
 * The assertion this component exists for: an unconfigured machine shows *no*
 * rate, not a zero. Everything else here — the component parts beside the
 * total, the named missing inputs, the refusal of a zero lifetime — is in
 * service of the same thing, which is that the rate can be checked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { PrinterCostPolicyForm } from './PrinterCostPolicyForm'
import { pricingApi } from '@/lib/api/pricing'
import type { PrinterCostPolicy } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getPrinterCostPolicy: vi.fn(),
    updatePrinterCostPolicy: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)
const PRINTER_ID = 'printer-1'

/** The golden case's machine: CA$1,100 over 6,000 h, CA$220 reserve, 95 W. */
function configured(overrides: Partial<PrinterCostPolicy> = {}): PrinterCostPolicy {
  return {
    printer_id: PRINTER_ID,
    purchase_price: '1100.00',
    expected_lifetime_hours: 6000,
    maintenance_reserve_total: '220.00',
    measured_watts: '95.00',
    electricity_rate_per_kwh: '0.1300',
    effective_electricity_rate_per_kwh: '0.1300',
    machine_rate_per_hour: '0.23235',
    components: {
      depreciation_per_hour: '0.18333',
      maintenance_per_hour: '0.03667',
      power_per_hour: '0.01235',
    },
    missing: [],
    ...overrides,
  }
}

/** A printer nobody has entered a policy for. */
function unconfigured(): PrinterCostPolicy {
  return {
    printer_id: PRINTER_ID,
    purchase_price: null,
    expected_lifetime_hours: null,
    maintenance_reserve_total: null,
    measured_watts: null,
    electricity_rate_per_kwh: null,
    effective_electricity_rate_per_kwh: null,
    machine_rate_per_hour: null,
    components: {},
    missing: ['expected_lifetime_hours', 'purchase_price', 'measured_watts'],
  }
}

function renderForm(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('PrinterCostPolicyForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getPrinterCostPolicy.mockResolvedValue(configured())
    mocked.updatePrinterCostPolicy.mockResolvedValue(configured())
  })

  it('reports the derived rate', async () => {
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('derived-rate')).toHaveTextContent('$0.23')
    })
  })

  it('shows the parts the rate is made of, so it needs no recomputing', async () => {
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    // Scoped to the derived-rate panel: "Maintenance reserve" is also a form
    // field label further down, and the claim here is about the breakdown.
    await waitFor(() => {
      expect(screen.getByTestId('derived-rate')).toBeInTheDocument()
    })
    const panel = within(screen.getByTestId('derived-rate'))
    expect(panel.getByText('Depreciation')).toBeInTheDocument()
    expect(panel.getByText('$0.18')).toBeInTheDocument()
    expect(panel.getByText('Maintenance reserve')).toBeInTheDocument()
    expect(panel.getByText('Power')).toBeInTheDocument()
  })

  it('loads the figures already entered', async () => {
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    await waitFor(() => {
      expect(screen.getByLabelText('Purchase price')).toHaveValue('1100.00')
    })
    expect(screen.getByLabelText('Expected printing hours')).toHaveValue('6000')
  })

  describe('a machine nobody has costed', () => {
    beforeEach(() => {
      mocked.getPrinterCostPolicy.mockResolvedValue(unconfigured())
    })

    it('says the rate is not yet known rather than showing zero', async () => {
      renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

      await waitFor(() => {
        expect(screen.getByTestId('rate-unknown')).toHaveTextContent('not yet known')
      })
      expect(screen.getByTestId('derived-rate')).not.toHaveTextContent('$0.00')
    })

    it('names what it still needs, in words rather than field names', async () => {
      renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

      await waitFor(() => {
        expect(screen.getByTestId('missing-inputs')).toBeInTheDocument()
      })
      const missing = screen.getByTestId('missing-inputs')
      expect(missing).toHaveTextContent('what the machine cost to buy')
      expect(missing).toHaveTextContent('how many printing hours you expect from it')
      expect(missing).not.toHaveTextContent('purchase_price')
    })
  })

  it('shows no missing-inputs note once the rate is complete', async () => {
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('printer-cost-policy-form')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('missing-inputs')).not.toBeInTheDocument()
  })

  it('refuses a lifetime of zero, which is a division and not a rate', async () => {
    const user = userEvent.setup({ delay: null })
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    const hours = await screen.findByLabelText('Expected printing hours')
    await user.clear(hours)
    await user.type(hours, '0')
    await user.click(screen.getByRole('button', { name: /Save machine cost/ }))

    await waitFor(() => {
      expect(
        screen.getByText(/depreciation over zero hours is not a rate/),
      ).toBeInTheDocument()
    })
    expect(mocked.updatePrinterCostPolicy).not.toHaveBeenCalled()
  })

  it('refuses a negative purchase price', async () => {
    const user = userEvent.setup({ delay: null })
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    const price = await screen.findByLabelText('Purchase price')
    await user.clear(price)
    await user.type(price, '-1')
    await user.click(screen.getByRole('button', { name: /Save machine cost/ }))

    await waitFor(() => {
      expect(screen.getByText(/Enter a non-negative amount/)).toBeInTheDocument()
    })
    expect(mocked.updatePrinterCostPolicy).not.toHaveBeenCalled()
  })

  it('sends money as the decimal string it was typed as', async () => {
    const user = userEvent.setup({ delay: null })
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    const price = await screen.findByLabelText('Purchase price')
    await user.clear(price)
    await user.type(price, '1250.50')
    await user.click(screen.getByRole('button', { name: /Save machine cost/ }))

    await waitFor(() => {
      expect(mocked.updatePrinterCostPolicy).toHaveBeenCalled()
    })
    const [, changes] = mocked.updatePrinterCostPolicy.mock.calls[0]
    expect(changes.purchase_price).toBe('1250.50')
  })

  it('does not erase a figure the operator left blank', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.getPrinterCostPolicy.mockResolvedValue(
      configured({ measured_watts: null, missing: ['measured_watts'] }),
    )
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    const price = await screen.findByLabelText('Purchase price')
    await user.clear(price)
    await user.type(price, '1250.50')
    await user.click(screen.getByRole('button', { name: /Save machine cost/ }))

    await waitFor(() => {
      expect(mocked.updatePrinterCostPolicy).toHaveBeenCalled()
    })
    const [, changes] = mocked.updatePrinterCostPolicy.mock.calls[0]
    expect(changes).not.toHaveProperty('measured_watts')
  })

  it('says where the electricity rate comes from when the printer has none', async () => {
    mocked.getPrinterCostPolicy.mockResolvedValue(
      configured({
        electricity_rate_per_kwh: null,
        effective_electricity_rate_per_kwh: '0.1300',
      }),
    )
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    await waitFor(() => {
      expect(screen.getByText(/Currently using \$0.13 from there/)).toBeInTheDocument()
    })
  })

  it('names the printer when it is given one', async () => {
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} printerName="Bambu A1 Mini" />)

    await waitFor(() => {
      expect(screen.getByText(/Bambu A1 Mini/)).toBeInTheDocument()
    })
  })

  it('lets a member read the rate but not change it', async () => {
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} canEdit={false} />)

    await waitFor(() => {
      expect(screen.getByTestId('read-only-notice')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Purchase price')).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Save machine cost/ })).not.toBeInTheDocument()
  })

  it('reports a failed save instead of appearing to have saved', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.updatePrinterCostPolicy.mockRejectedValue(new Error('Requires admin role or higher'))
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    const price = await screen.findByLabelText('Purchase price')
    await user.clear(price)
    await user.type(price, '1250.50')
    await user.click(screen.getByRole('button', { name: /Save machine cost/ }))

    await waitFor(() => {
      expect(screen.getByText('Requires admin role or higher')).toBeInTheDocument()
    })
  })

  it('reports a failed load instead of an empty form', async () => {
    mocked.getPrinterCostPolicy.mockRejectedValue(new Error('boom'))
    renderForm(<PrinterCostPolicyForm printerId={PRINTER_ID} />)

    await waitFor(() => {
      expect(
        screen.getByText("Failed to load this printer's cost policy"),
      ).toBeInTheDocument()
    })
  })
})
