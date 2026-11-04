/** Carrier postage API client (spec 006). */

import { apiClient } from '../api'
import type {
  CarrierApply,
  CarrierApplyResult,
  CarriersResponse,
  PostageSettings,
  TariffUpdate,
} from '@/types/postageCatalogue'

export const postageCatalogueApi = {
  carriers: (): Promise<CarriersResponse> =>
    apiClient.get<CarriersResponse>('/api/v1/postage/carriers'),

  apply: (data: CarrierApply): Promise<CarrierApplyResult> =>
    apiClient.post<CarrierApplyResult>('/api/v1/postage/carriers/apply', data),

  tariffUpdates: async (): Promise<TariffUpdate[]> =>
    (await apiClient.get<{ updates: TariffUpdate[] }>('/api/v1/postage/tariff-updates')).updates,

  removeService: (service: string): Promise<void> =>
    apiClient.delete<void>(`/api/v1/postage/carriers/services/${encodeURIComponent(service)}`),

  setDefaultService: (defaultService: string | null): Promise<PostageSettings> =>
    apiClient.put<PostageSettings>('/api/v1/settings/postage', { default_service: defaultService }),
}
