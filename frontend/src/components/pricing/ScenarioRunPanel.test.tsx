/**
 * Tests for the scenario panel's job states (T119a, FR-044b).
 *
 * A background job's states are the interface, not an implementation detail,
 * and each one here exists to prevent a specific way of misleading an
 * operator:
 *
 * - **queued** must say nothing has been calculated. A panel that showed an
 *   empty result table for a queued run would read as "no product falls below
 *   your floor", which is the opposite of the truth.
 * - **running** must not look stuck, and must say a bigger catalogue takes
 *   longer rather than failing (FR-044e).
 * - **partial** must show what it got *and* what it missed. Reporting only the
 *   gap throws away a usable answer; reporting only the answer hides the gap.
 * - **failed** must show the reason. A job that stops silently is the one
 *   outcome FR-044b forbids outright.
 *
 * And across all of them: a finished run states the shock and inputs it ran
 * with (FR-044c), because a result read a fortnight later is otherwise
 * indistinguishable from a report on today's figures.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ScenarioRunPanel } from './ScenarioRunPanel'
import * as pricingApi from '@/lib/api/pricing'
import type { ScenarioRun, ScenarioState } from '@/types/pricing'

vi.mock('@/lib/api/pricing', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/pricing')>('@/lib/api/pricing')
  return {
    ...actual,
    requestScenario: vi.fn(),
    getScenario: vi.fn(),
    listScenarios: vi.fn(),
  }
})

function belowFloorEntry(overrides: Record<string, unknown> = {}) {
  return {
    product_id: 'prod-1',
    sku: 'DRAGON-01',
    name: 'Articulated dragon',
    sales_channel_id: 'chan-1',
    channel_name: 'Etsy',
    list_price: '64.99',
    make_cost: '25.38',
    margin_pct: '12.4000',
    profit: '8.06',
    profit_per_machine_hour: '0.85',
    shortfall_pct: '7.6000',
    ...overrides,
  }
}

function run(state: ScenarioState, overrides: Partial<ScenarioRun> = {}): ScenarioRun {
  const terminal = state === 'succeeded' || state === 'partial' || state === 'failed'
  return {
    id: 'run-1',
    state,
    shock: { material_cost_pct: '25', labor_rate_pct: '0' },
    margin_floor_pct: '20',
    inputs: { as_of: '2026-10-13', margin_basis: 'customer_total', labor_rate: '25.00' },
    result:
      terminal && state !== 'failed'
        ? {
            shock: { material_cost_pct: '25' },
            inputs: {
              as_of: '2026-10-13',
              margin_basis: 'customer_total',
              labor_rate: '25.00',
              margin_floor_pct: '20',
            },
            evaluated: 42,
            below_floor: [belowFloorEntry()],
            skipped: state === 'partial' ? [{ ...skipped() }] : [],
          }
        : null,
    error_text: state === 'failed' ? 'the costing engine stopped: filament cost missing' : null,
    requested_at: '2026-10-13T09:00:00Z',
    started_at: state === 'queued' ? null : '2026-10-13T09:00:05Z',
    finished_at: terminal ? '2026-10-13T09:04:11Z' : null,
    ...overrides,
  }
}

function skipped() {
  return {
    product_id: 'prod-9',
    sku: 'BUNDLE-09',
    sales_channel_id: 'chan-1',
    reason: 'BUNDLE-09 is in its own hierarchy',
  }
}

function renderPanel(props: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ScenarioRunPanel {...props} />
      </QueryClientProvider>,
    ),
  }
}

/** Requests a scenario and waits for the watched run to appear. */
async function requestAndWatch(state: ScenarioState, overrides: Partial<ScenarioRun> = {}) {
  vi.mocked(pricingApi.requestScenario).mockResolvedValue(run('queued'))
  vi.mocked(pricingApi.getScenario).mockResolvedValue(run(state, overrides))
  const user = userEvent.setup()
  const rendered = renderPanel()

  await user.click(screen.getByRole('button', { name: /run the scenario/i }))
  await screen.findByTestId('scenario-run')
  return { user, ...rendered }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(pricingApi.listScenarios).mockResolvedValue({ runs: [], total: 0 })
})

// ---------------------------------------------------------------------------
// Asking
// ---------------------------------------------------------------------------

describe('requesting a scenario', () => {
  it('says that nothing will be changed by it', async () => {
    // The sentence that decides whether an operator dares press the button.
    renderPanel()

    expect(screen.getByText(/no cost, price or origin is written/i)).toBeInTheDocument()
  })

  it('sends the shock and the floor the operator entered', async () => {
    vi.mocked(pricingApi.requestScenario).mockResolvedValue(run('queued'))
    const user = userEvent.setup()
    renderPanel()

    await user.clear(screen.getByLabelText(/material cost change/i))
    await user.type(screen.getByLabelText(/material cost change/i), '40')
    await user.clear(screen.getByLabelText(/margin floor/i))
    await user.type(screen.getByLabelText(/margin floor/i), '15')
    await user.click(screen.getByRole('button', { name: /run the scenario/i }))

    await waitFor(() => {
      expect(pricingApi.requestScenario).toHaveBeenCalledWith({
        shock: { material_cost_pct: '40' },
        margin_floor_pct: '15',
        sales_channel_id: undefined,
      })
    })
  })

  it('sends the percentages as strings', async () => {
    // Constitution IV: a percentage parsed into a number here arrives at the
    // engine as a float, and the engine's whole point is exact arithmetic.
    vi.mocked(pricingApi.requestScenario).mockResolvedValue(run('queued'))
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: /run the scenario/i }))

    await waitFor(() => {
      const payload = vi.mocked(pricingApi.requestScenario).mock.calls[0][0]
      expect(typeof payload.margin_floor_pct).toBe('string')
      expect(typeof payload.shock.material_cost_pct).toBe('string')
    })
  })

  it('limits the sweep to a channel when given one', async () => {
    vi.mocked(pricingApi.requestScenario).mockResolvedValue(run('queued'))
    const user = userEvent.setup()
    renderPanel({ salesChannelId: 'chan-7' })

    await user.click(screen.getByRole('button', { name: /run the scenario/i }))

    await waitFor(() => {
      expect(vi.mocked(pricingApi.requestScenario).mock.calls[0][0].sales_channel_id).toBe(
        'chan-7',
      )
    })
  })

  it('reports a refused request without implying anything changed', async () => {
    vi.mocked(pricingApi.requestScenario).mockRejectedValue(new Error('422'))
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole('button', { name: /run the scenario/i }))

    expect(await screen.findByTestId('scenario-request-error')).toHaveTextContent(
      /nothing was changed/i,
    )
  })
})

// ---------------------------------------------------------------------------
// The four states
// ---------------------------------------------------------------------------

describe('a queued run', () => {
  it('shows the queued state', async () => {
    await requestAndWatch('queued')

    expect(screen.getByTestId('scenario-state-queued')).toBeInTheDocument()
  })

  it('says nothing has been calculated yet', async () => {
    // An empty result table here would read as "no product falls below your
    // floor", which is the opposite of the truth.
    await requestAndWatch('queued')

    expect(screen.getByText(/nothing has been calculated yet/i)).toBeInTheDocument()
    expect(screen.queryByTestId('scenario-below-floor')).not.toBeInTheDocument()
    expect(screen.queryByTestId('scenario-none-below-floor')).not.toBeInTheDocument()
  })
})

describe('a running run', () => {
  it('shows the running state', async () => {
    await requestAndWatch('running')

    expect(screen.getByTestId('scenario-state-running')).toBeInTheDocument()
  })

  it('says a larger catalogue takes longer rather than failing', async () => {
    // FR-044e. Without it, a long sweep reads as a hung job.
    await requestAndWatch('running')

    expect(screen.getByText(/does not fail/i)).toBeInTheDocument()
  })

  it('shows no result while it is still working', async () => {
    await requestAndWatch('running')

    expect(screen.queryByTestId('scenario-below-floor')).not.toBeInTheDocument()
  })
})

describe('a finished run', () => {
  it('names the products below the floor', async () => {
    // A count sends an operator hunting; the names are the answer.
    await requestAndWatch('succeeded')

    const table = await screen.findByTestId('scenario-below-floor')
    expect(within(table).getByText('Articulated dragon')).toBeInTheDocument()
    expect(within(table).getByText('DRAGON-01')).toBeInTheDocument()
  })

  it('reports how many were costed', async () => {
    await requestAndWatch('succeeded')

    expect(await screen.findByTestId('scenario-evaluated')).toHaveTextContent('42')
  })

  it('shows profit per machine-hour beside the margin', async () => {
    // FR-043: the figure that decides what is worth the machine time.
    await requestAndWatch('succeeded')

    const table = await screen.findByTestId('scenario-below-floor')
    expect(within(table).getByText('0.85')).toBeInTheDocument()
    expect(within(table).getByText(/12\.4%/)).toBeInTheDocument()
  })

  it('calls an undefined margin undefined rather than zero', async () => {
    // Fees consuming the whole basis. A 0% would read as break-even.
    await requestAndWatch('succeeded', {
      result: {
        shock: { material_cost_pct: '25' },
        inputs: { as_of: '2026-10-13' },
        evaluated: 1,
        below_floor: [belowFloorEntry({ margin_pct: null })],
        skipped: [],
      },
    })

    const table = await screen.findByTestId('scenario-below-floor')
    expect(within(table).getByText('undefined')).toBeInTheDocument()
  })

  it('says so plainly when nothing fell below the floor', async () => {
    await requestAndWatch('succeeded', {
      result: {
        shock: { material_cost_pct: '25' },
        inputs: { as_of: '2026-10-13' },
        evaluated: 42,
        below_floor: [],
        skipped: [],
      },
    })

    expect(await screen.findByTestId('scenario-none-below-floor')).toBeInTheDocument()
  })

  it('states the shock it ran with', async () => {
    // FR-044c. The single most important thing on an old result.
    await requestAndWatch('succeeded')

    const provenance = await screen.findByTestId('scenario-inputs')
    expect(provenance.textContent).toMatch(/material cost 25\.0%/i)
  })

  it('states the inputs it ran against', async () => {
    await requestAndWatch('succeeded')

    const provenance = await screen.findByTestId('scenario-inputs')
    expect(provenance.textContent).toContain('customer_total')
    expect(provenance.textContent).toContain('25.00')
  })

  it('says the figures are not today-s', async () => {
    await requestAndWatch('succeeded')

    expect(
      await screen.findByText(/figures the run used, not today's/i),
    ).toBeInTheDocument()
  })

  it('shows when it finished', async () => {
    await requestAndWatch('succeeded')

    expect(await screen.findByText(/finished 2026-10-13T09:04:11Z/)).toBeInTheDocument()
  })
})

describe('a partial run', () => {
  it('shows the partial state', async () => {
    await requestAndWatch('partial')

    expect(screen.getByTestId('scenario-state-partial')).toBeInTheDocument()
  })

  it('still reports what it got', async () => {
    // Half an answer beats none, which is the whole reason `partial` exists.
    await requestAndWatch('partial')

    expect(await screen.findByTestId('scenario-below-floor')).toBeInTheDocument()
    expect(await screen.findByTestId('scenario-evaluated')).toHaveTextContent('42')
  })

  it('names what it could not cost, and why', async () => {
    await requestAndWatch('partial')

    const gap = await screen.findByTestId('scenario-skipped')
    expect(gap.textContent).toContain('BUNDLE-09')
    expect(gap.textContent).toContain('own hierarchy')
  })
})

describe('a failed run', () => {
  it('shows the failed state', async () => {
    await requestAndWatch('failed')

    expect(screen.getByTestId('scenario-state-failed')).toBeInTheDocument()
  })

  it('shows the reason it stopped', async () => {
    // FR-044b: a job that stops silently is worse than one that fails loudly.
    await requestAndWatch('failed')

    expect(await screen.findByTestId('scenario-error')).toHaveTextContent(
      /filament cost missing/,
    )
  })

  it('shows no result table', async () => {
    await requestAndWatch('failed')

    expect(screen.queryByTestId('scenario-below-floor')).not.toBeInTheDocument()
  })

  it('still states what it was asked', async () => {
    // A failure whose question is lost cannot be retried knowingly.
    await requestAndWatch('failed')

    expect(await screen.findByTestId('scenario-inputs')).toBeInTheDocument()
  })

  it('does not blame the operator for a missing reason', async () => {
    await requestAndWatch('failed', { error_text: null })

    expect(await screen.findByTestId('scenario-error')).toHaveTextContent(
      /without recording a reason/i,
    )
  })
})

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

describe('earlier scenarios', () => {
  it('lists them with their shock and state', async () => {
    vi.mocked(pricingApi.listScenarios).mockResolvedValue({
      runs: [run('succeeded'), run('failed', { id: 'run-2' })],
      total: 2,
    })
    renderPanel()

    const history = await screen.findByTestId('scenario-history')
    expect(history.textContent).toMatch(/material cost 25\.0%/i)
    expect(history.textContent).toMatch(/Finished/)
    expect(history.textContent).toMatch(/Stopped/)
  })

  it('opens one when it is chosen', async () => {
    vi.mocked(pricingApi.listScenarios).mockResolvedValue({
      runs: [run('succeeded', { id: 'run-5' })],
      total: 1,
    })
    vi.mocked(pricingApi.getScenario).mockResolvedValue(run('succeeded', { id: 'run-5' }))
    const user = userEvent.setup()
    renderPanel()

    const history = await screen.findByTestId('scenario-history')
    await user.click(within(history).getByRole('button'))

    await waitFor(() => {
      expect(pricingApi.getScenario).toHaveBeenCalledWith('run-5')
    })
  })

  it('is absent when nothing has been run', async () => {
    renderPanel()

    await waitFor(() => {
      expect(screen.queryByTestId('scenario-history')).not.toBeInTheDocument()
    })
  })
})
