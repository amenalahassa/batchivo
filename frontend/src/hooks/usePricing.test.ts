/**
 * usePricing tests.
 *
 * The behaviour worth pinning here is the invalidation. A labor rate or a
 * machine rate reaches every cost on every screen, so writing one has to
 * discard the cached figures — a stale cost left on display is precisely the
 * defect this feature set out to remove (Constitution V).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'

import {
  pricingKeys,
  useModelCost,
  usePrinterCostPolicy,
  useProductCost,
  useSaveFilamentPurchase,
  useUpdatePricingPolicy,
  useUpdatePrinterCostPolicy,
} from './usePricing'
import { pricingApi } from '@/lib/api/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getModelCost: vi.fn(),
    getProductCost: vi.fn(),
    getPricingPolicy: vi.fn(),
    updatePricingPolicy: vi.fn(),
    getPrinterCostPolicy: vi.fn(),
    updatePrinterCostPolicy: vi.fn(),
    listFilamentPurchases: vi.fn(),
    getFilamentPurchase: vi.fn(),
    createFilamentPurchase: vi.fn(),
    updateFilamentPurchase: vi.fn(),
    deleteFilamentPurchase: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)

function harness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)
  return { queryClient, wrapper }
}

describe('pricingKeys', () => {
  it('separates a model cost on one printer from the same model on another', () => {
    expect(pricingKeys.modelCost('m1', 'p1')).not.toEqual(pricingKeys.modelCost('m1', 'p2'))
  })

  it('separates an as-of policy read from the current one', () => {
    expect(pricingKeys.policy('2024-06-01')).not.toEqual(pricingKeys.policy())
  })
})

describe('useModelCost', () => {
  beforeEach(() => vi.clearAllMocks())

  it('does not fetch without a model id', () => {
    const { wrapper } = harness()
    renderHook(() => useModelCost(undefined), { wrapper })
    expect(mocked.getModelCost).not.toHaveBeenCalled()
  })

  it('passes the printer through, since the rate depends on the machine', async () => {
    mocked.getModelCost.mockResolvedValue({ total_make_cost: '20.30' } as never)
    const { wrapper } = harness()

    const { result } = renderHook(() => useModelCost('m1', 'p1'), { wrapper })

    await waitFor(() => expect(result.current.breakdown).toBeDefined())
    expect(mocked.getModelCost).toHaveBeenCalledWith('m1', 'p1')
  })
})

describe('useProductCost', () => {
  beforeEach(() => vi.clearAllMocks())

  it('does not fetch without a product id', () => {
    const { wrapper } = harness()
    renderHook(() => useProductCost(undefined), { wrapper })
    expect(mocked.getProductCost).not.toHaveBeenCalled()
  })
})

describe('usePrinterCostPolicy', () => {
  beforeEach(() => vi.clearAllMocks())

  it('does not fetch without a printer id', () => {
    const { wrapper } = harness()
    renderHook(() => usePrinterCostPolicy(undefined), { wrapper })
    expect(mocked.getPrinterCostPolicy).not.toHaveBeenCalled()
  })
})

describe('useUpdatePricingPolicy', () => {
  beforeEach(() => vi.clearAllMocks())

  it('discards every cached cost, because a labor rate reaches all of them', async () => {
    mocked.updatePricingPolicy.mockResolvedValue({ print_labor_rate: '30' } as never)
    const { queryClient, wrapper } = harness()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useUpdatePricingPolicy(), { wrapper })
    await result.current.updatePolicyAsync({ print_labor_rate: '30' })

    await waitFor(() => expect(invalidate).toHaveBeenCalled())
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey?.[0])
    expect(keys).toContain('pricing')
    expect(keys).toContain('products')
    expect(keys).toContain('models')
  })
})

describe('useUpdatePrinterCostPolicy', () => {
  beforeEach(() => vi.clearAllMocks())

  it('discards cached costs, because the machine rate changes what it prints', async () => {
    mocked.updatePrinterCostPolicy.mockResolvedValue({ printer_id: 'p1' } as never)
    const { queryClient, wrapper } = harness()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useUpdatePrinterCostPolicy('p1'), { wrapper })
    await result.current.updateCostPolicyAsync({ purchase_price: '1100.00' })

    await waitFor(() => expect(invalidate).toHaveBeenCalled())
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey?.[0])
    expect(keys).toContain('pricing')
    expect(keys).toContain('printers')
  })

  it('writes to the printer it was built for', async () => {
    mocked.updatePrinterCostPolicy.mockResolvedValue({ printer_id: 'p1' } as never)
    const { wrapper } = harness()

    const { result } = renderHook(() => useUpdatePrinterCostPolicy('p1'), { wrapper })
    await result.current.updateCostPolicyAsync({ measured_watts: '95' })

    expect(mocked.updatePrinterCostPolicy).toHaveBeenCalledWith('p1', { measured_watts: '95' })
  })
})

describe('useSaveFilamentPurchase', () => {
  beforeEach(() => vi.clearAllMocks())

  it('discards cached spool costs, since the allocation is derived on read', async () => {
    mocked.createFilamentPurchase.mockResolvedValue({ id: 'purchase-1' } as never)
    const { queryClient, wrapper } = harness()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useSaveFilamentPurchase(), { wrapper })
    await result.current.createPurchaseAsync({ purchase_date: '2026-03-01' })

    await waitFor(() => expect(invalidate).toHaveBeenCalled())
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey?.[0])
    expect(keys).toContain('pricing')
    expect(keys).toContain('spools')
  })

  it('does the same after a correction, which re-splits every sibling’s share', async () => {
    mocked.updateFilamentPurchase.mockResolvedValue({ id: 'purchase-1' } as never)
    const { queryClient, wrapper } = harness()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useSaveFilamentPurchase(), { wrapper })
    await result.current.updatePurchaseAsync({
      purchaseId: 'purchase-1',
      data: { inbound_shipping_cost: '36.00' },
    })

    await waitFor(() => expect(invalidate).toHaveBeenCalled())
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey?.[0])
    expect(keys).toContain('spools')
  })
})
