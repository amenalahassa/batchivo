/**
 * The breakdown reaches a page, with the operator's own staleness threshold
 * (task T128).
 *
 * `CostBreakdownPanel` was tested in isolation and imported nowhere, so FR-018
 * (every line itemised with its origin), FR-046 (the observed share) and
 * SC-004 (100% of lines display an origin and a date) held in a component no
 * operator could open. This section is what the product and model pages mount.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { CostBreakdownSection } from './CostBreakdownSection'
import { pricingApi } from '@/lib/api/pricing'
import type { CostBreakdown, CostLine, PricingPolicy } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getProductCost: vi.fn(),
    getModelCost: vi.fn(),
    getPricingPolicy: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)

function line(overrides: Partial<CostLine> = {}): CostLine {
  return {
    key: 'material',
    label: 'Filament in the part',
    amount: '4.52',
    risk_class: 'at_risk',
    source: 'observed',
    as_of: '2026-03-01',
    has_pending_revision: false,
    ...overrides,
  }
}

function breakdown(overrides: Partial<CostBreakdown> = {}): CostBreakdown {
  return {
    lines: [line()],
    at_risk_subtotal: '19.38',
    not_at_risk_subtotal: '0.92',
    yield_applied: '0.9200',
    failure_mode: 'per_part',
    failure_premium: '1.68',
    total_make_cost: '20.30',
    observed_share: '0.70',
    assumed_share: '0.30',
    incomplete_reasons: [],
    ...overrides,
  }
}

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
    effective_from: '2026-03-01',
    effective_to: null,
    set_by_role: 'admin',
    ...overrides,
  }
}

function renderSection(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('CostBreakdownSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getProductCost.mockResolvedValue(breakdown())
    mocked.getModelCost.mockResolvedValue(breakdown())
    mocked.getPricingPolicy.mockResolvedValue(policy())
  })

  it('fetches and renders a product’s breakdown', async () => {
    renderSection(<CostBreakdownSection productId="product-1" />)

    expect(await screen.findByTestId('cost-breakdown-panel')).toBeInTheDocument()
    expect(mocked.getProductCost).toHaveBeenCalledWith('product-1')
    expect(mocked.getModelCost).not.toHaveBeenCalled()
  })

  it('fetches and renders a model’s breakdown, at a given printer’s rate', async () => {
    // FR-011: an item is costed at the rate of the machine it is planned on.
    renderSection(<CostBreakdownSection modelId="model-1" printerId="printer-3" />)

    expect(await screen.findByTestId('cost-breakdown-panel')).toBeInTheDocument()
    expect(mocked.getModelCost).toHaveBeenCalledWith('model-1', 'printer-3')
    expect(mocked.getProductCost).not.toHaveBeenCalled()
  })

  it('passes the operator’s staleness threshold, never a constant', async () => {
    // FR-005 makes the threshold the operator's. A figure flagged stale
    // against a number nobody set is a warning nobody can act on.
    mocked.getPricingPolicy.mockResolvedValue(policy({ staleness_threshold_days: 30 }))
    mocked.getProductCost.mockResolvedValue(
      breakdown({
        lines: [line({ source: 'measured', as_of: '2020-01-01' })],
      })
    )

    renderSection(<CostBreakdownSection productId="product-1" />)

    // A measurement from 2020 is past any threshold, so the panel warns.
    expect(await screen.findByTestId('cost-breakdown-panel')).toBeInTheDocument()
    await waitFor(() => {
      expect(mocked.getPricingPolicy).toHaveBeenCalled()
    })
    expect(screen.getByText(/stale/i)).toBeInTheDocument()
  })

  it('reports a failed fetch rather than showing a cost of zero', async () => {
    // FR-019's principle: a cost that could not be worked out is reported as
    // such. Zero is a number an operator would price against.
    mocked.getProductCost.mockRejectedValue(new Error('the engine is unreachable'))

    renderSection(<CostBreakdownSection productId="product-1" />)

    expect(await screen.findByText(/no cost to show/i)).toBeInTheDocument()
    expect(screen.queryByTestId('cost-breakdown-panel')).not.toBeInTheDocument()
  })

  it('shows the amounts in the tenant’s currency', async () => {
    renderSection(<CostBreakdownSection productId="product-1" currencySymbol="CA$" />)

    expect(await screen.findByText(/CA\$20\.30/)).toBeInTheDocument()
  })
})
