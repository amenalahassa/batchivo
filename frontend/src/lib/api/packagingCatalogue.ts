/** Standard packaging catalogue and seeding notice API client (spec 006). */

import { apiClient } from '../api'
import type {
  CatalogueApplyResult,
  CatalogueNotice,
  NoticePart,
  PackagingCatalogue,
} from '@/types/packagingCatalogue'

export const packagingCatalogueApi = {
  get: (): Promise<PackagingCatalogue> =>
    apiClient.get<PackagingCatalogue>('/api/v1/packaging/catalogue'),

  /** No keys (or an empty list) adds every item not yet present. */
  apply: (keys?: string[]): Promise<CatalogueApplyResult> =>
    apiClient.post<CatalogueApplyResult>('/api/v1/packaging/catalogue/apply', { keys: keys ?? null }),

  notice: (): Promise<CatalogueNotice> => apiClient.get<CatalogueNotice>('/api/v1/catalogue-notice'),

  acknowledge: (part: NoticePart): Promise<void> =>
    apiClient.post<void>('/api/v1/catalogue-notice/acknowledge', { part }),
}
