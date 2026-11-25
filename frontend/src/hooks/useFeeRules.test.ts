/**
 * useFeeRules tests (task T085).
 *
 * What matters about these hooks is not that they fetch, but **what they
 * invalidate**. A fee rule reaches every product priced on that channel, so a
 * rule change has to invalidate every margin, not just the one on screen: a
 * stale margin beside a changed rule is how an operator stops trusting the
 * figures entirely.
 *
 * The other thing asserted here is that nothing is optimistic. A margin is
 * derived (Constitution V), so predicting one locally would be showing a
 * percentage nothing computed.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'
import {
  feeKeys,
  useChannelPnL,
  useCreateFeeRule,
  useDeleteFeeRule,
  useFeePreview,
  useFeeRules,
  useProductMargin,
  useRecordFeeActual,
  useShippingProfiles,
  useUpdateFeeRule,
} from './useFeeRules'

const api = {
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  preview: vi.fn(),
  getMargin: vi.fn(),
  recordFeeActual: vi.fn(),
  getChannelPnL: vi.fn(),
  listShippingProfiles: vi.fn(),
  createShippingProfile: vi.fn(),
  updateShippingProfile: vi.fn(),
  deleteShippingProfile: vi.fn(),
}

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: {
    list: (...a: unknown[]) => api.list(...a),
    create: (...a: unknown[]) => api.create(...a),
    update: (...a: unknown[]) => api.update(...a),
    remove: (...a: unknown[]) => api.remove(...a),
    preview: (...a: unknown[]) => api.preview(...a),
    getMargin: (...a: unknown[]) => api.getMargin(...a),
    recordFeeActual: (...a: unknown[]) => api.recordFeeActual(...a),
    getChannelPnL: (...a: unknown[]) => api.getChannelPnL(...a),
    listShippingProfiles: (...a: unknown[]) => api.listShippingProfiles(...a),
    createShippingProfile: (...a: unknown[]) => api.createShippingProfile(...a),
    updateShippingProfile: (...a: unknown[]) => api.updateShippingProfile(...a),
    deleteShippingProfile: (...a: unknown[]) => api.deleteShippingProfile(...a),
  },
}))

const CHANNEL_ID = 'channel-1'

function harness() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)
  return { queryClient, wrapper }
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.list.mockResolvedValue({ rules: [], total: 0, as_of: '2026-06-01' })
  api.create.mockResolvedValue({ id: 'rule-1' })
  api.update.mockResolvedValue({ id: 'rule-1' })
  api.remove.mockResolvedValue(undefined)
  api.preview.mockResolvedValue({ charges: [], total: '0.00', periodic: [] })
  api.getMargin.mockResolvedValue({ margin_pct: '35.2693' })
  api.recordFeeActual.mockResolvedValue({ id: 'actual-1' })
  api.getChannelPnL.mockResolvedValue({ order_count: 0 })
  api.listShippingProfiles.mockResolvedValue({ profiles: [], total: 0 })
})

describe('query keys', () => {
  it('separates an as-of read from the current one', () => {
    expect(feeKeys.rules(CHANNEL_ID)).not.toEqual(feeKeys.rules(CHANNEL_ID, '2024-03-01'))
  })

  it('separates a margin by product, channel, date and quantity', () => {
    expect(feeKeys.margin('p', 'c')).not.toEqual(feeKeys.margin('p', 'c2'))
    expect(feeKeys.margin('p', 'c', '2024-01-01')).not.toEqual(feeKeys.margin('p', 'c'))
    expect(feeKeys.margin('p', 'c', undefined, 3)).not.toEqual(feeKeys.margin('p', 'c'))
  })
})

describe('useFeeRules', () => {
  it('does not fetch without a channel', () => {
    const { wrapper } = harness()
    renderHook(() => useFeeRules(undefined), { wrapper })

    expect(api.list).not.toHaveBeenCalled()
  })

  it('returns an empty list rather than undefined before it loads', () => {
    const { wrapper } = harness()
    const { result } = renderHook(() => useFeeRules(CHANNEL_ID), { wrapper })

    expect(result.current.rules).toEqual([])
  })

  it('passes an as-of date through', async () => {
    const { wrapper } = harness()
    renderHook(() => useFeeRules(CHANNEL_ID, '2024-03-01'), { wrapper })

    await waitFor(() => expect(api.list).toHaveBeenCalledWith(CHANNEL_ID, '2024-03-01'))
  })
})

describe('writing a fee rule invalidates every margin', () => {
  it('invalidates on create', async () => {
    const { queryClient, wrapper } = harness()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useCreateFeeRule(CHANNEL_ID), { wrapper })

    result.current.mutate({ name: 'transaction', basis: 'order_total', applies_from: '2026-01-01' })

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toEqual(
      expect.arrayContaining([
        ['fees', 'rules', CHANNEL_ID],
        ['fees', 'margin'],
        ['fees', 'channel-pnl', CHANNEL_ID],
      ]),
    )
  })

  it('invalidates on update', async () => {
    const { queryClient, wrapper } = harness()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useUpdateFeeRule(CHANNEL_ID), { wrapper })

    result.current.mutate({ ruleId: 'rule-1', data: { rate_pct: '7' } })

    await waitFor(() =>
      expect(spy.mock.calls.map((c) => c[0]?.queryKey)).toEqual(
        expect.arrayContaining([['fees', 'margin']]),
      ),
    )
  })

  it('invalidates on delete', async () => {
    const { queryClient, wrapper } = harness()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useDeleteFeeRule(CHANNEL_ID), { wrapper })

    result.current.mutate('rule-1')

    await waitFor(() =>
      expect(spy.mock.calls.map((c) => c[0]?.queryKey)).toEqual(
        expect.arrayContaining([['fees', 'margin']]),
      ),
    )
  })

  it('writes no optimistic margin', async () => {
    // A margin is derived, never stored. The cache must hold nothing for a
    // margin key until the server answers one.
    const { queryClient, wrapper } = harness()
    const { result } = renderHook(() => useCreateFeeRule(CHANNEL_ID), { wrapper })

    result.current.mutate({ name: 'fee', basis: 'order_total', applies_from: '2026-01-01' })

    await waitFor(() => expect(api.create).toHaveBeenCalled())
    expect(queryClient.getQueryData(feeKeys.margin('p', CHANNEL_ID))).toBeUndefined()
  })
})

describe('useProductMargin', () => {
  it('does not fetch until both a product and a channel are known', () => {
    const { wrapper } = harness()
    renderHook(() => useProductMargin(undefined, CHANNEL_ID), { wrapper })
    renderHook(() => useProductMargin('product-1', undefined), { wrapper })

    expect(api.getMargin).not.toHaveBeenCalled()
  })

  it('fetches once both are known', async () => {
    const { wrapper } = harness()
    renderHook(() => useProductMargin('product-1', CHANNEL_ID), { wrapper })

    await waitFor(() =>
      expect(api.getMargin).toHaveBeenCalledWith('product-1', CHANNEL_ID, undefined),
    )
  })

  it('passes an as-of date and a quantity through', async () => {
    const { wrapper } = harness()
    renderHook(
      () => useProductMargin('product-1', CHANNEL_ID, { asOf: '2024-03-01', quantity: 3 }),
      { wrapper },
    )

    await waitFor(() =>
      expect(api.getMargin).toHaveBeenCalledWith('product-1', CHANNEL_ID, {
        asOf: '2024-03-01',
        quantity: 3,
      }),
    )
  })
})

describe('useFeePreview', () => {
  it('is a mutation, so a changed input is never answered from cache', async () => {
    const { wrapper } = harness()
    const { result } = renderHook(() => useFeePreview(CHANNEL_ID), { wrapper })

    result.current.mutate({ item_subtotal: '64.99' })
    await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(1))

    result.current.mutate({ item_subtotal: '70.00' })
    await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(2))
  })
})

describe('useChannelPnL', () => {
  it('does not fetch until the whole period is known', () => {
    const { wrapper } = harness()
    renderHook(
      () => useChannelPnL({ channelId: CHANNEL_ID, periodStart: '2026-06-01', periodEnd: undefined }),
      { wrapper },
    )

    expect(api.getChannelPnL).not.toHaveBeenCalled()
  })

  it('fetches once the period is complete', async () => {
    const { wrapper } = harness()
    renderHook(
      () =>
        useChannelPnL({
          channelId: CHANNEL_ID,
          periodStart: '2026-06-01',
          periodEnd: '2026-06-30',
        }),
      { wrapper },
    )

    await waitFor(() =>
      expect(api.getChannelPnL).toHaveBeenCalledWith({
        channelId: CHANNEL_ID,
        periodStart: '2026-06-01',
        periodEnd: '2026-06-30',
      }),
    )
  })
})

describe('useRecordFeeActual', () => {
  it('invalidates the P&L for the channel it was recorded against', async () => {
    const { queryClient, wrapper } = harness()
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useRecordFeeActual(), { wrapper })

    result.current.mutate({
      sales_channel_id: CHANNEL_ID,
      fee_category: 'transaction',
      amount: '7.00',
      period_start: '2026-06-01',
      period_end: '2026-06-30',
    })

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({
        queryKey: ['fees', 'channel-pnl', CHANNEL_ID],
      }),
    )
  })
})

describe('useShippingProfiles', () => {
  it('returns an empty list before it loads', () => {
    const { wrapper } = harness()
    const { result } = renderHook(() => useShippingProfiles(), { wrapper })

    expect(result.current.profiles).toEqual([])
  })

  it('passes a zone filter through', async () => {
    const { wrapper } = harness()
    renderHook(() => useShippingProfiles('us'), { wrapper })

    await waitFor(() => expect(api.listShippingProfiles).toHaveBeenCalledWith('us'))
  })
})
