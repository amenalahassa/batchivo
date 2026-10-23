/**
 * The machine cost policy has a door (task T130).
 *
 * `PrinterCostPolicyForm` was built and unit-tested, but nothing imported it,
 * so the per-machine rate FR-010 and FR-011 require could not be set from the
 * console. These tests assert the door exists, that it carries the printer it
 * was opened for, and that a viewer meets it read-only rather than shut.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { PrinterCostPolicyDialog } from './PrinterCostPolicyDialog'
import { pricingApi } from '@/lib/api/pricing'
import type { PrinterCostPolicy } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getPrinterCostPolicy: vi.fn(),
    updatePrinterCostPolicy: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)

function policy(overrides: Partial<PrinterCostPolicy> = {}): PrinterCostPolicy {
  return {
    printer_id: 'printer-1',
    purchase_price: '1100.00',
    expected_lifetime_hours: 6000,
    maintenance_reserve_total: '220.00',
    measured_watts: '95.00',
    electricity_rate_per_kwh: '0.1300',
    effective_electricity_rate_per_kwh: '0.1300',
    machine_rate_per_hour: '0.23235',
    components: {},
    missing: [],
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('PrinterCostPolicyDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getPrinterCostPolicy.mockResolvedValue(policy())
  })

  it('names the printer whose rate is being set', async () => {
    // FR-011: the rate is per machine, so a dialog that does not say which
    // machine invites the operator to set the wrong one.
    renderDialog(
      <PrinterCostPolicyDialog
        open
        onOpenChange={vi.fn()}
        printerId="printer-1"
        printerName="Bambu X1C"
      />
    )

    expect(
      await screen.findByRole('heading', { name: /machine cost — bambu x1c/i })
    ).toBeInTheDocument()
  })

  it('loads that printer’s policy', async () => {
    renderDialog(
      <PrinterCostPolicyDialog open onOpenChange={vi.fn()} printerId="printer-7" />
    )

    await waitFor(() => {
      expect(mocked.getPrinterCostPolicy).toHaveBeenCalledWith('printer-7')
    })
  })

  it('renders nothing for the form while no printer is selected', async () => {
    renderDialog(<PrinterCostPolicyDialog open onOpenChange={vi.fn()} printerId={null} />)

    expect(screen.queryByTestId('printer-cost-policy-form')).not.toBeInTheDocument()
    expect(mocked.getPrinterCostPolicy).not.toHaveBeenCalled()
  })

  it('shows a viewer the rate with the controls disabled', async () => {
    renderDialog(
      <PrinterCostPolicyDialog
        open
        onOpenChange={vi.fn()}
        printerId="printer-1"
        canEdit={false}
      />
    )

    const price = await screen.findByLabelText(/purchase price/i)
    expect(price).toBeDisabled()
  })

  it('lets an admin edit the rate', async () => {
    renderDialog(
      <PrinterCostPolicyDialog open onOpenChange={vi.fn()} printerId="printer-1" canEdit />
    )

    expect(await screen.findByLabelText(/purchase price/i)).toBeEnabled()
  })
})
