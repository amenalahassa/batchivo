/**
 * Packaging advisor hooks (feature 003).
 *
 * Suggestions are computed on request and never cached as a fact (FR-022):
 * they are fetched only when the operator asks, and a change of dimensions or
 * packaging invalidates them along with the product.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { pricingKeys } from '@/hooks/usePricing'
import {
  acceptPackaging,
  confirmOrderParcels,
  getOrderPackagingSuggestions,
  getPackagingSettings,
  getPackagingSuggestions,
  setModelDimensions,
  setProductDimensions,
  setVariantDimensions,
  updatePackagingSettings,
} from '@/lib/api/packaging'
import type {
  AcceptPackagingInput,
  ConfirmParcelsInput,
  DimensionsInput,
  PackagingSettingsInput,
} from '@/types/packaging'

export const packagingKeys = {
  suggestions: (productId: string, variantId?: string | null) =>
    ['packaging', 'suggestions', productId, variantId ?? 'product'] as const,
  settings: ['packaging', 'settings'] as const,
  order: (orderId: string) => ['packaging', 'order', orderId] as const,
}

/** Which record a set of dimensions belongs to. */
export type DimensionsTarget =
  | { kind: 'product'; productId: string }
  | { kind: 'variant'; productId: string; variantId: string }
  | { kind: 'model'; modelId: string }

export function useSetDimensions(target: DimensionsTarget) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: DimensionsInput) => {
      switch (target.kind) {
        case 'product':
          return setProductDimensions(target.productId, data)
        case 'variant':
          return setVariantDimensions(target.productId, target.variantId, data)
        case 'model':
          return setModelDimensions(target.modelId, data)
      }
    },
    onSuccess: () => {
      if (target.kind === 'model') {
        queryClient.invalidateQueries({ queryKey: ['model', target.modelId] })
        queryClient.invalidateQueries({ queryKey: ['models'] })
        return
      }
      queryClient.invalidateQueries({ queryKey: ['product', target.productId] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.invalidateQueries({ queryKey: ['packaging', 'suggestions', target.productId] })
    },
  })
}

export function usePackagingSuggestions(
  productId: string,
  variantId: string | null | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: packagingKeys.suggestions(productId, variantId),
    queryFn: () => getPackagingSuggestions(productId, variantId),
    enabled,
  })
}

export function useAcceptPackaging(productId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: AcceptPackagingInput) => acceptPackaging(productId, data),
    onSuccess: () => {
      // The packaging line of the cost breakdown moves with the accepted box.
      queryClient.invalidateQueries({ queryKey: ['product', productId] })
      queryClient.invalidateQueries({ queryKey: ['packaging', 'suggestions', productId] })
      queryClient.invalidateQueries({ queryKey: pricingKeys.productCost(productId) })
    },
  })
}

export function usePackagingSettings() {
  return useQuery({ queryKey: packagingKeys.settings, queryFn: getPackagingSettings })
}

export function useUpdatePackagingSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: PackagingSettingsInput) => updatePackagingSettings(data),
    onSuccess: (saved) => {
      queryClient.setQueryData(packagingKeys.settings, saved)
      queryClient.invalidateQueries({ queryKey: ['packaging', 'suggestions'] })
    },
  })
}

export function useOrderPackagingSuggestions(orderId: string, enabled: boolean) {
  return useQuery({
    queryKey: packagingKeys.order(orderId),
    queryFn: () => getOrderPackagingSuggestions(orderId),
    enabled,
  })
}

export function useConfirmOrderParcels(orderId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ConfirmParcelsInput) => confirmOrderParcels(orderId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['order', orderId] })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['consumables'] })
    },
  })
}
