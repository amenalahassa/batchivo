import { apiClient } from '../api'
import type { FxWaitingLines, ManualFxRate, ManualFxRateCreate } from '@/types/pricing'

/**
 * Exchange rates entered by hand (task T223, FR-028h).
 *
 * The rate is sent as the decimal string it was typed as, never a number: a
 * rate moves every margin built on it (Constitution IV).
 */
export const fxRatesApi = {
  /** Settled lines that froze no rate, with the currency pair each waits on. */
  waiting: async (): Promise<FxWaitingLines> =>
    apiClient.get<FxWaitingLines>('/api/v1/fx-rates/waiting'),

  /** Record a manual rate; it fills only lines that froze none (FR-028j). */
  recordManual: async (body: ManualFxRateCreate): Promise<ManualFxRate> =>
    apiClient.post<ManualFxRate>('/api/v1/fx-rates/manual', body),
}
