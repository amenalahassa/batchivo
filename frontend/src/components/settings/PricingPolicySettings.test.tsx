/**
 * PricingPolicySettings tests.
 *
 * What matters on this screen is not that the inputs render — it is that a
 * fallback is labelled as one, that a capacity of zero is refused before it
 * becomes a divisor, and that only the levers the operator touched are sent,
 * so saving a labor rate does not quietly clear an overhead pool.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { PricingPolicySettings } from './PricingPolicySettings'
import { pricingApi } from '@/lib/api/pricing'
import type { PricingPolicy } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getPricingPolicy: vi.fn(),
    updatePricingPolicy: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)

function policy(overrides: Partial<PricingPolicy> = {}): PricingPolicy {
  return {
    print_labor_rate: '25.0000',
    finishing_labor_rate: '25.0000',
    default_machine_rate_per_hour: '0.2324',
    overhead_method: 'per_machine_hour',
    overhead_monthly_pool: '180.0000',
    expected_monthly_machine_hours: '600.0000',
    overhead_rate_per_machine_hour: '0.30',
    overhead_percentage: '0',
    electricity_rate_per_kwh: '0.1300',
    margin_basis: 'customer_total',
    default_target_margin_pct: '35',
    rounding_rule: null,
    sales_tax_recoverable: false,
    staleness_threshold_days: 180,
    margin_alert_threshold_pct: '5',
    min_outcomes_before_auto_update: 5,
    estimate_divergence_threshold_pct: '25',
    origin: 'policy_row',
    source: 'policy',
    effective_from: '2026-03-01',
    effective_to: null,
    set_by_role: 'admin',
    ...overrides,
  }
}

function renderPolicy(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('PricingPolicySettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getPricingPolicy.mockResolvedValue(policy())
    mocked.updatePricingPolicy.mockResolvedValue(policy())
  })

  it('loads the policy the operator configured', async () => {
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByLabelText('Print handling rate (per hour)')).toHaveValue('25.0000')
    })
  })

  it('says when it is in effect and who set it', async () => {
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByTestId('effective-from')).toHaveTextContent('2026-03-01')
    })
    expect(screen.getByTestId('effective-from')).toHaveTextContent('admin')
  })

  it('labels a legacy fallback as a fallback rather than as a decision', async () => {
    mocked.getPricingPolicy.mockResolvedValue(
      policy({ origin: 'legacy_settings', effective_from: null, set_by_role: null }),
    )
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByTestId('legacy-origin-notice')).toBeInTheDocument()
    })
    expect(screen.getByText('These are fallback figures')).toBeInTheDocument()
    expect(screen.queryByTestId('effective-from')).not.toBeInTheDocument()
  })

  it('shows no fallback notice once the policy is the operator’s own', async () => {
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByTestId('pricing-policy-settings')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('legacy-origin-notice')).not.toBeInTheDocument()
  })

  it('reports the overhead currently absorbed per machine-hour', async () => {
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByText(/Currently absorbing \$0.30 per machine-hour/)).toBeInTheDocument()
    })
  })

  it('refuses a capacity of zero before it becomes a divisor', async () => {
    const user = userEvent.setup({ delay: null })
    renderPolicy(<PricingPolicySettings />)

    const capacity = await screen.findByLabelText('Expected machine-hours a month')
    await user.clear(capacity)
    await user.type(capacity, '0')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(screen.getByText(/a capacity of zero is a misconfiguration/)).toBeInTheDocument()
    })
    expect(mocked.updatePricingPolicy).not.toHaveBeenCalled()
  })

  it('refuses a negative labor rate', async () => {
    const user = userEvent.setup({ delay: null })
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText('Print handling rate (per hour)')
    await user.clear(rate)
    await user.type(rate, '-5')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(screen.getByText('Enter a non-negative hourly rate')).toBeInTheDocument()
    })
    expect(mocked.updatePricingPolicy).not.toHaveBeenCalled()
  })

  it('sends the rate as the decimal string it was typed as, not a number', async () => {
    const user = userEvent.setup({ delay: null })
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText('Print handling rate (per hour)')
    await user.clear(rate)
    await user.type(rate, '32.50')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(mocked.updatePricingPolicy).toHaveBeenCalled()
    })
    const sent = mocked.updatePricingPolicy.mock.calls[0][0]
    expect(sent.print_labor_rate).toBe('32.50')
    expect(typeof sent.print_labor_rate).toBe('string')
  })

  it('does not send a lever the operator left blank', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.getPricingPolicy.mockResolvedValue(
      policy({ default_machine_rate_per_hour: null, overhead_method: 'percentage' }),
    )
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText('Print handling rate (per hour)')
    await user.clear(rate)
    await user.type(rate, '30')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(mocked.updatePricingPolicy).toHaveBeenCalled()
    })
    const sent = mocked.updatePricingPolicy.mock.calls[0][0]
    expect(sent).not.toHaveProperty('default_machine_rate_per_hour')
  })

  it('hides the overhead pool fields under the percentage method', async () => {
    mocked.getPricingPolicy.mockResolvedValue(policy({ overhead_method: 'percentage' }))
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByTestId('pricing-policy-settings')).toBeInTheDocument()
    })
    expect(screen.queryByLabelText('Monthly overhead')).not.toBeInTheDocument()
  })

  it('offers the overhead percentage under the percentage method and sends it as typed', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.getPricingPolicy.mockResolvedValue(
      policy({ overhead_method: 'percentage', overhead_percentage: '10' }),
    )
    renderPolicy(<PricingPolicySettings />)

    const percentage = await screen.findByLabelText('Overhead percentage')
    expect(percentage).toHaveValue('10')
    await user.clear(percentage)
    await user.type(percentage, '12.5')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(mocked.updatePricingPolicy).toHaveBeenCalled()
    })
    expect(mocked.updatePricingPolicy.mock.calls[0][0].overhead_percentage).toBe('12.5')
  })

  it('does not re-send an overhead percentage nobody changed', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.getPricingPolicy.mockResolvedValue(
      policy({ overhead_method: 'percentage', overhead_percentage: '10' }),
    )
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText('Print handling rate (per hour)')
    await user.clear(rate)
    await user.type(rate, '30')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(mocked.updatePricingPolicy).toHaveBeenCalled()
    })
    expect(mocked.updatePricingPolicy.mock.calls[0][0]).not.toHaveProperty('overhead_percentage')
  })

  it('sends only the lever that moved, never the rest of the form (T260)', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.getPricingPolicy.mockResolvedValue(policy({ overhead_method: 'percentage' }))
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText('Print handling rate (per hour)')
    await user.clear(rate)
    await user.type(rate, '30')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(mocked.updatePricingPolicy).toHaveBeenCalled()
    })
    expect(mocked.updatePricingPolicy.mock.calls[0][0]).toEqual({ print_labor_rate: '30' })
  })

  it('shows each lever with its own origin (T260)', async () => {
    mocked.getPricingPolicy.mockResolvedValue(
      policy({
        source: 'policy',
        levers: {
          margin_basis: { source: 'policy', as_of: '2026-10-20', set_by_role: 'owner' },
          print_labor_rate: { source: 'assumed', as_of: null, set_by_role: null },
        },
      }),
    )
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText(/Print handling rate/)
    const rateLabel = document.querySelector(`label[for="${rate.id}"]`)
    expect(rateLabel?.textContent).toMatch(/assumed|default/i)
    expect(rateLabel?.textContent).not.toMatch(/policy/i)
  })

  it('says when nobody has set the policy yet', async () => {
    mocked.getPricingPolicy.mockResolvedValue(policy({ source: 'assumed', set_by_role: null }))
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByTestId('assumed-policy-notice')).toBeInTheDocument()
    })
  })

  it('does not call a policy an operator set an assumption', async () => {
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByTestId('pricing-policy-settings')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('assumed-policy-notice')).not.toBeInTheDocument()
  })

  it('lets a viewer read the policy but not change it', async () => {
    renderPolicy(<PricingPolicySettings canEdit={false} />)

    await waitFor(() => {
      expect(screen.getByTestId('read-only-notice')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Print handling rate (per hour)')).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Save pricing policy/ })).not.toBeInTheDocument()
  })

  it('reports a failed save instead of appearing to have saved', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.updatePricingPolicy.mockRejectedValue(new Error('Requires admin role or higher'))
    renderPolicy(<PricingPolicySettings />)

    const rate = await screen.findByLabelText('Print handling rate (per hour)')
    await user.clear(rate)
    await user.type(rate, '30')
    await user.click(screen.getByRole('button', { name: /Save pricing policy/ }))

    await waitFor(() => {
      expect(screen.getByText('Requires admin role or higher')).toBeInTheDocument()
    })
  })

  it('reports a failed load instead of an empty form', async () => {
    mocked.getPricingPolicy.mockRejectedValue(new Error('boom'))
    renderPolicy(<PricingPolicySettings />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load your pricing policy')).toBeInTheDocument()
    })
  })
})
