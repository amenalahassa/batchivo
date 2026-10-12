import { apiClient } from '../api'
import type {
  CostBreakdown,
  FilamentPurchase,
  FilamentPurchaseCreate,
  FilamentPurchaseListResponse,
  FilamentPurchaseUpdate,
  PricingPolicy,
  PricingPolicyUpdate,
  PrinterCostPolicy,
  PrinterCostPolicyUpdate,
} from '@/types/pricing'

/**
 * Pricing and costing API client.
 *
 * Every money field in these payloads is a decimal **string** and stays one:
 * nothing here parses an amount into a number (Constitution IV). Components
 * render the string or hand it to a decimal library.
 */
export const pricingApi = {
  /**
   * The itemised make-cost of one printed item.
   *
   * `printerId` costs the item at the rate of the machine it is planned on;
   * omitted, the policy's default machine rate applies.
   */
  getModelCost: async (modelId: string, printerId?: string): Promise<CostBreakdown> => {
    const query = printerId ? `?printer_id=${encodeURIComponent(printerId)}` : ''
    return apiClient.get<CostBreakdown>(`/api/v1/models/${modelId}/cost${query}`)
  },

  /** The itemised make-cost of one sellable unit, bundles included. */
  getProductCost: async (productId: string): Promise<CostBreakdown> => {
    return apiClient.get<CostBreakdown>(`/api/v1/products/${productId}/cost`)
  },

  /**
   * The pricing policy in effect, today or on `asOf`.
   *
   * An `asOf` read answers "what was the labor rate when this order was
   * placed", which is the question the policy table exists for.
   */
  getPricingPolicy: async (asOf?: string): Promise<PricingPolicy> => {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
    return apiClient.get<PricingPolicy>(`/api/v1/settings/pricing-policy${query}`)
  },

  /**
   * Change one or more levers. Requires admin or owner.
   *
   * This writes a new effective row rather than editing one, so the rate a
   * past order was costed at stays readable.
   */
  updatePricingPolicy: async (changes: PricingPolicyUpdate): Promise<PricingPolicy> => {
    return apiClient.put<PricingPolicy>('/api/v1/settings/pricing-policy', changes)
  },

  /** A printer's machine cost policy, with the rate's component parts. */
  getPrinterCostPolicy: async (printerId: string): Promise<PrinterCostPolicy> => {
    return apiClient.get<PrinterCostPolicy>(`/api/v1/printers/${printerId}/cost-policy`)
  },

  /** Set a printer's machine cost policy. Fields left out are not touched. */
  updatePrinterCostPolicy: async (
    printerId: string,
    changes: PrinterCostPolicyUpdate,
  ): Promise<PrinterCostPolicy> => {
    return apiClient.put<PrinterCostPolicy>(
      `/api/v1/printers/${printerId}/cost-policy`,
      changes,
    )
  },

  listFilamentPurchases: async (params?: {
    skip?: number
    limit?: number
  }): Promise<FilamentPurchaseListResponse> => {
    const query = new URLSearchParams()
    if (params?.skip !== undefined) query.append('skip', params.skip.toString())
    if (params?.limit !== undefined) query.append('limit', params.limit.toString())
    const queryString = query.toString()
    return apiClient.get<FilamentPurchaseListResponse>(
      `/api/v1/filament-purchases${queryString ? `?${queryString}` : ''}`,
    )
  },

  getFilamentPurchase: async (purchaseId: string): Promise<FilamentPurchase> => {
    return apiClient.get<FilamentPurchase>(`/api/v1/filament-purchases/${purchaseId}`)
  },

  createFilamentPurchase: async (data: FilamentPurchaseCreate): Promise<FilamentPurchase> => {
    return apiClient.post<FilamentPurchase>('/api/v1/filament-purchases', data)
  },

  updateFilamentPurchase: async (
    purchaseId: string,
    data: FilamentPurchaseUpdate,
  ): Promise<FilamentPurchase> => {
    return apiClient.put<FilamentPurchase>(`/api/v1/filament-purchases/${purchaseId}`, data)
  },

  deleteFilamentPurchase: async (purchaseId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/filament-purchases/${purchaseId}`)
  },
}
