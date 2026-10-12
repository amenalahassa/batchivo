/**
 * pricingApi tests.
 *
 * A thin client, so what is checked is thin too — the URLs, the query
 * parameters, and the one property that matters throughout: a money field
 * passes through as the string it arrived as. Nothing here may call Number()
 * on an amount (Constitution IV).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { pricingApi } from './pricing'
import { apiClient } from '../api'

vi.mock('../api', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

const mocked = vi.mocked(apiClient)

describe('pricingApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.get.mockResolvedValue({} as never)
    mocked.post.mockResolvedValue({} as never)
    mocked.put.mockResolvedValue({} as never)
    mocked.delete.mockResolvedValue(undefined as never)
  })

  describe('costs', () => {
    it('reads a model cost', async () => {
      await pricingApi.getModelCost('m1')
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/models/m1/cost')
    })

    it('costs a model on a named printer when one is given', async () => {
      await pricingApi.getModelCost('m1', 'p1')
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/models/m1/cost?printer_id=p1')
    })

    it('reads a product cost', async () => {
      await pricingApi.getProductCost('prod-1')
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/products/prod-1/cost')
    })

    it('returns the total as the decimal string the API sent', async () => {
      mocked.get.mockResolvedValue({ total_make_cost: '20.30' } as never)
      const breakdown = await pricingApi.getProductCost('prod-1')
      expect(breakdown.total_make_cost).toBe('20.30')
    })
  })

  describe('pricing policy', () => {
    it('reads the current policy', async () => {
      await pricingApi.getPricingPolicy()
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/settings/pricing-policy')
    })

    it('reads the policy in effect on a past date', async () => {
      await pricingApi.getPricingPolicy('2024-06-01')
      expect(mocked.get).toHaveBeenCalledWith(
        '/api/v1/settings/pricing-policy?as_of=2024-06-01',
      )
    })

    it('sends only the levers it was given', async () => {
      await pricingApi.updatePricingPolicy({ print_labor_rate: '25.00' })
      expect(mocked.put).toHaveBeenCalledWith('/api/v1/settings/pricing-policy', {
        print_labor_rate: '25.00',
      })
    })
  })

  describe('printer cost policy', () => {
    it('reads one printer’s policy', async () => {
      await pricingApi.getPrinterCostPolicy('p1')
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/printers/p1/cost-policy')
    })

    it('writes one printer’s policy', async () => {
      await pricingApi.updatePrinterCostPolicy('p1', { purchase_price: '1100.00' })
      expect(mocked.put).toHaveBeenCalledWith('/api/v1/printers/p1/cost-policy', {
        purchase_price: '1100.00',
      })
    })
  })

  describe('filament purchases', () => {
    it('lists purchases', async () => {
      await pricingApi.listFilamentPurchases()
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/filament-purchases')
    })

    it('passes pagination through', async () => {
      await pricingApi.listFilamentPurchases({ skip: 20, limit: 10 })
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/filament-purchases?skip=20&limit=10')
    })

    it('passes a skip of zero rather than dropping it', async () => {
      await pricingApi.listFilamentPurchases({ skip: 0 })
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/filament-purchases?skip=0')
    })

    it('reads one purchase', async () => {
      await pricingApi.getFilamentPurchase('purchase-1')
      expect(mocked.get).toHaveBeenCalledWith('/api/v1/filament-purchases/purchase-1')
    })

    it('creates a purchase', async () => {
      await pricingApi.createFilamentPurchase({ purchase_date: '2026-03-01' })
      expect(mocked.post).toHaveBeenCalledWith('/api/v1/filament-purchases', {
        purchase_date: '2026-03-01',
      })
    })

    it('updates a purchase', async () => {
      await pricingApi.updateFilamentPurchase('purchase-1', { tax_amount: '6.00' })
      expect(mocked.put).toHaveBeenCalledWith('/api/v1/filament-purchases/purchase-1', {
        tax_amount: '6.00',
      })
    })

    it('deletes a purchase', async () => {
      await pricingApi.deleteFilamentPurchase('purchase-1')
      expect(mocked.delete).toHaveBeenCalledWith('/api/v1/filament-purchases/purchase-1')
    })

    it('keeps an allocated share exact rather than parsing it', async () => {
      mocked.get.mockResolvedValue({
        spools: [{ allocated_shipping: '1.3846153846153846' }],
      } as never)
      const purchase = await pricingApi.getFilamentPurchase('purchase-1')
      expect(purchase.spools[0].allocated_shipping).toBe('1.3846153846153846')
    })
  })
})
