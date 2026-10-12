/**
 * Pricing and costing hooks.
 *
 * A cost is derived, never stored (Constitution V), so these are plain queries
 * with no optimistic cost anywhere: showing a predicted figure would be
 * showing one nothing computed. Writing a policy invalidates every cost, since
 * a labor rate reaches all of them.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { pricingApi } from '@/lib/api/pricing'
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

export const pricingKeys = {
  modelCost: (modelId: string, printerId?: string) =>
    ['pricing', 'model-cost', modelId, printerId ?? null] as const,
  productCost: (productId: string) => ['pricing', 'product-cost', productId] as const,
  policy: (asOf?: string) => ['pricing', 'policy', asOf ?? 'current'] as const,
  printerCostPolicy: (printerId: string) =>
    ['pricing', 'printer-cost-policy', printerId] as const,
  filamentPurchases: () => ['pricing', 'filament-purchases'] as const,
  filamentPurchase: (purchaseId: string) =>
    ['pricing', 'filament-purchase', purchaseId] as const,
}

/** The itemised make-cost of one printed item, optionally on a given printer. */
export function useModelCost(modelId: string | undefined, printerId?: string) {
  const query = useQuery<CostBreakdown>({
    queryKey: pricingKeys.modelCost(modelId ?? '', printerId),
    queryFn: () => pricingApi.getModelCost(modelId as string, printerId),
    enabled: Boolean(modelId),
  })

  return {
    breakdown: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/** The itemised make-cost of one sellable unit. */
export function useProductCost(productId: string | undefined) {
  const query = useQuery<CostBreakdown>({
    queryKey: pricingKeys.productCost(productId ?? ''),
    queryFn: () => pricingApi.getProductCost(productId as string),
    enabled: Boolean(productId),
  })

  return {
    breakdown: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/** The pricing policy in effect, today or on `asOf`. */
export function usePricingPolicy(asOf?: string) {
  const query = useQuery<PricingPolicy>({
    queryKey: pricingKeys.policy(asOf),
    queryFn: () => pricingApi.getPricingPolicy(asOf),
  })

  return {
    policy: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/**
 * Change policy levers.
 *
 * Invalidates every cached cost as well as the policy: a labor rate or an
 * overhead method reaches every figure on every screen, and leaving a stale
 * one on display is the defect this feature set out to remove.
 */
export function useUpdatePricingPolicy() {
  const queryClient = useQueryClient()

  const mutation = useMutation<PricingPolicy, Error, PricingPolicyUpdate>({
    mutationFn: (changes) => pricingApi.updatePricingPolicy(changes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pricing'] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
  })

  return {
    updatePolicy: mutation.mutate,
    updatePolicyAsync: mutation.mutateAsync,
    isUpdating: mutation.isPending,
    error: mutation.error,
  }
}

/** A printer's machine cost policy and the hourly rate it implies. */
export function usePrinterCostPolicy(printerId: string | undefined) {
  const query = useQuery<PrinterCostPolicy>({
    queryKey: pricingKeys.printerCostPolicy(printerId ?? ''),
    queryFn: () => pricingApi.getPrinterCostPolicy(printerId as string),
    enabled: Boolean(printerId),
  })

  return {
    costPolicy: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

export function useUpdatePrinterCostPolicy(printerId: string) {
  const queryClient = useQueryClient()

  const mutation = useMutation<PrinterCostPolicy, Error, PrinterCostPolicyUpdate>({
    mutationFn: (changes) => pricingApi.updatePrinterCostPolicy(printerId, changes),
    onSuccess: () => {
      // A machine rate changes the cost of everything printed on it.
      queryClient.invalidateQueries({ queryKey: ['pricing'] })
      queryClient.invalidateQueries({ queryKey: ['printers'] })
    },
  })

  return {
    updateCostPolicy: mutation.mutate,
    updateCostPolicyAsync: mutation.mutateAsync,
    isUpdating: mutation.isPending,
    error: mutation.error,
  }
}

export function useFilamentPurchases(params?: { skip?: number; limit?: number }) {
  const query = useQuery<FilamentPurchaseListResponse>({
    queryKey: [...pricingKeys.filamentPurchases(), params?.skip ?? 0, params?.limit ?? 50],
    queryFn: () => pricingApi.listFilamentPurchases(params),
  })

  return {
    purchases: query.data?.purchases ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

export function useFilamentPurchase(purchaseId: string | undefined) {
  const query = useQuery<FilamentPurchase>({
    queryKey: pricingKeys.filamentPurchase(purchaseId ?? ''),
    queryFn: () => pricingApi.getFilamentPurchase(purchaseId as string),
    enabled: Boolean(purchaseId),
  })

  return {
    purchase: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/**
 * Record or correct a filament purchase.
 *
 * Spool costs are invalidated too: the allocation is derived on read, so
 * adding a spool or correcting the shipping changes every sibling's share.
 */
export function useSaveFilamentPurchase() {
  const queryClient = useQueryClient()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['pricing'] })
    queryClient.invalidateQueries({ queryKey: ['spools'] })
  }

  const create = useMutation<FilamentPurchase, Error, FilamentPurchaseCreate>({
    mutationFn: (data) => pricingApi.createFilamentPurchase(data),
    onSuccess: invalidate,
  })

  const update = useMutation<
    FilamentPurchase,
    Error,
    { purchaseId: string; data: FilamentPurchaseUpdate }
  >({
    mutationFn: ({ purchaseId, data }) => pricingApi.updateFilamentPurchase(purchaseId, data),
    onSuccess: invalidate,
  })

  const remove = useMutation<void, Error, string>({
    mutationFn: (purchaseId) => pricingApi.deleteFilamentPurchase(purchaseId),
    onSuccess: invalidate,
  })

  return {
    createPurchase: create.mutate,
    createPurchaseAsync: create.mutateAsync,
    updatePurchase: update.mutate,
    updatePurchaseAsync: update.mutateAsync,
    deletePurchase: remove.mutate,
    isSaving: create.isPending || update.isPending || remove.isPending,
    error: create.error ?? update.error ?? remove.error,
  }
}
