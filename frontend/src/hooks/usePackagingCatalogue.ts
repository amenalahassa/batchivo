/**
 * Standard packaging catalogue hooks (spec 006).
 *
 * Applying the catalogue adds consumables, so it invalidates every
 * `consumables` query (the Packaging and Consumables pages) and the notice.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { packagingCatalogueApi } from '@/lib/api/packagingCatalogue'
import type { NoticePart } from '@/types/packagingCatalogue'

export const packagingCatalogueKeys = {
  catalogue: ['packaging-catalogue'] as const,
  notice: ['catalogue-notice'] as const,
}

export function usePackagingCatalogue(enabled = true) {
  const query = useQuery({
    queryKey: packagingCatalogueKeys.catalogue,
    queryFn: packagingCatalogueApi.get,
    enabled,
  })
  return { catalogue: query.data, isLoading: query.isLoading, error: query.error }
}

export function useApplyPackagingCatalogue() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keys?: string[]) => packagingCatalogueApi.apply(keys),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['consumables'] })
      queryClient.invalidateQueries({ queryKey: packagingCatalogueKeys.catalogue })
      queryClient.invalidateQueries({ queryKey: packagingCatalogueKeys.notice })
    },
  })
}

export function useCatalogueNotice() {
  const query = useQuery({
    queryKey: packagingCatalogueKeys.notice,
    queryFn: packagingCatalogueApi.notice,
  })
  return { notice: query.data, isLoading: query.isLoading }
}

export function useAcknowledgeNotice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (part: NoticePart) => packagingCatalogueApi.acknowledge(part),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: packagingCatalogueKeys.notice }),
  })
}
