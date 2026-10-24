/**
 * Manual exchange-rate hooks (task T223).
 *
 * Recording a rate fills lines that froze none, so every reader of a settled
 * margin -- the divergence panel, an order's lines, a channel's P&L -- is
 * invalidated with the waiting list.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fxRatesApi } from '@/lib/api/fxRates'
import type { FxWaitingLines, ManualFxRate, ManualFxRateCreate } from '@/types/pricing'

export const fxKeys = {
  waiting: ['fx-rates', 'waiting'] as const,
}

export function useFxWaitingLines() {
  return useQuery<FxWaitingLines>({
    queryKey: fxKeys.waiting,
    queryFn: () => fxRatesApi.waiting(),
  })
}

export function useRecordManualFxRate() {
  const queryClient = useQueryClient()
  return useMutation<ManualFxRate, Error, ManualFxRateCreate>({
    mutationFn: (body) => fxRatesApi.recordManual(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: fxKeys.waiting })
      queryClient.invalidateQueries({ queryKey: ['fees'] })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['order'] })
      queryClient.invalidateQueries({ queryKey: ['margin-divergence'] })
    },
  })
}
