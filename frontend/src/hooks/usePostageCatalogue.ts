/**
 * Carrier postage hooks (spec 006).
 *
 * Seeding or removing a service changes the shipping profiles every margin
 * prices postage from, so each mutation invalidates the profiles, the
 * carriers, the tariff offer, the notice and the pricing figures.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { packagingCatalogueKeys } from '@/hooks/usePackagingCatalogue'
import { postageCatalogueApi } from '@/lib/api/postageCatalogue'
import type { CarrierApply } from '@/types/postageCatalogue'

export const postageCatalogueKeys = {
  carriers: ['postage', 'carriers'] as const,
  tariffUpdates: ['postage', 'tariff-updates'] as const,
}

function invalidatePostage(queryClient: ReturnType<typeof useQueryClient>): void {
  queryClient.invalidateQueries({ queryKey: ['postage'] })
  queryClient.invalidateQueries({ queryKey: ['fees', 'shipping-profiles'] })
  queryClient.invalidateQueries({ queryKey: packagingCatalogueKeys.notice })
  queryClient.invalidateQueries({ queryKey: ['pricing'] })
  queryClient.invalidateQueries({ queryKey: ['consumables'] })
}

export function useCarriers(enabled = true) {
  const query = useQuery({
    queryKey: postageCatalogueKeys.carriers,
    queryFn: postageCatalogueApi.carriers,
    enabled,
  })
  return { carriers: query.data, isLoading: query.isLoading, error: query.error }
}

export function useTariffUpdates() {
  const query = useQuery({
    queryKey: postageCatalogueKeys.tariffUpdates,
    queryFn: postageCatalogueApi.tariffUpdates,
  })
  return { updates: query.data ?? [], isLoading: query.isLoading }
}

export function useApplyCarrier() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CarrierApply) => postageCatalogueApi.apply(data),
    onSuccess: () => invalidatePostage(queryClient),
  })
}

export function useRemoveService() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (service: string) => postageCatalogueApi.removeService(service),
    onSuccess: () => invalidatePostage(queryClient),
  })
}

export function useSetDefaultService() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (defaultService: string | null) =>
      postageCatalogueApi.setDefaultService(defaultService),
    onSuccess: () => invalidatePostage(queryClient),
  })
}
