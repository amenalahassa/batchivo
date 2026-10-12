/**
 * ChannelProfitabilityPanel tests.
 *
 * This component owns one decision — which period the P&L covers — so these
 * tests are about the ways that choice can be wrong:
 *
 * * **The default period is the current month to date**, built from local
 *   calendar parts. An ISO slice of a UTC instant names yesterday for the
 *   first hours of each day west of UTC, which would drop an order at a
 *   period boundary.
 * * **An inverted range asks the API for nothing** and says so. A period that
 *   ends before it starts cannot contain an order, and rendering an empty
 *   month for it would read as a channel that sold nothing.
 * * **A failed load shows no figures at all.** A partially-rendered P&L is
 *   the kind of figure an operator acts on and should not have.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@/test/test-utils'
import userEvent from '@testing-library/user-event'

import { ChannelProfitabilityPanel } from './ChannelProfitabilityPanel'
import type { ChannelPnL } from '@/types/pricing'

const getChannelPnLMock = vi.fn()

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: {
    getChannelPnL: (...args: unknown[]) => getChannelPnLMock(...args),
  },
}))

const CHANNEL_ID = 'channel-1'

function pnl(overrides: Partial<ChannelPnL> = {}): ChannelPnL {
  return {
    channel_id: CHANNEL_ID,
    period_start: '2026-03-01',
    period_end: '2026-03-14',
    order_count: 12,
    revenue_tax_exclusive: '640.00',
    sales_tax_collected: '83.20',
    sales_tax_liability: '0.00',
    postage_paid: '114.00',
    shipping_revenue: '0.00',
    shipping_net: '-114.00',
    planned_fee_total: '80.00',
    actual_fee_total: null,
    unallocated_remainder: '0.00',
    fee_difference: null,
    reconciliation: [],
    absorbed_costs: [],
    unabsorbed_total: '0.00',
    make_cost_total: '243.60',
    profit: '202.40',
    margin_pct: '31.6250',
    margin_basis: 'customer_total',
    margin_basis_label: 'customer total',
    ...overrides,
  }
}

beforeEach(() => {
  getChannelPnLMock.mockReset()
  getChannelPnLMock.mockResolvedValue(pnl())
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ChannelProfitabilityPanel', () => {
  it('asks for the current month to date, in local calendar terms', async () => {
    // 1 March 2026, 00:30 in a zone two hours behind UTC: toISOString() on
    // this instant would say 2026-03-01T02:30Z — the same day here, but the
    // same construction an hour earlier would have said February.
    // Only the clock is faked: the timers waitFor depends on stay real.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 2, 14, 0, 30))

    render(<ChannelProfitabilityPanel channelId={CHANNEL_ID} />)

    await waitFor(() => expect(getChannelPnLMock).toHaveBeenCalled())
    expect(getChannelPnLMock).toHaveBeenCalledWith({
      channelId: CHANNEL_ID,
      periodStart: '2026-03-01',
      periodEnd: '2026-03-14',
    })
  })

  it('renders the reconciliation once the period loads', async () => {
    render(<ChannelProfitabilityPanel channelId={CHANNEL_ID} currencySymbol="CA$" />)

    expect(await screen.findByText(/CA\$640\.00/)).toBeInTheDocument()
  })

  it('does not query an inverted period, and says why', async () => {
    const user = userEvent.setup()
    render(<ChannelProfitabilityPanel channelId={CHANNEL_ID} />)

    await waitFor(() => expect(getChannelPnLMock).toHaveBeenCalledTimes(1))
    getChannelPnLMock.mockClear()

    const start = screen.getByLabelText('Period start')
    await user.clear(start)
    await user.type(start, '2099-01-01')

    expect(await screen.findByTestId('pnl-period-inverted')).toBeInTheDocument()
    expect(getChannelPnLMock).not.toHaveBeenCalled()
  })

  it('shows no figures at all when the period fails to load', async () => {
    getChannelPnLMock.mockRejectedValue(new Error('upstream unavailable'))

    render(<ChannelProfitabilityPanel channelId={CHANNEL_ID} />)

    expect(await screen.findByTestId('pnl-error')).toHaveTextContent('upstream unavailable')
    expect(screen.queryByText(/640\.00/)).not.toBeInTheDocument()
  })
})
