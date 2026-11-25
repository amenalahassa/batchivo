/**
 * Generative AI API (spec 008, contracts/genai-api.md).
 */
import { apiClient } from '@/lib/api'
import type {
  AdoptRequest,
  AdoptResponse,
  CapabilitiesResponse,
  EstimateResponse,
  GenAIAsset,
  GenerationJob,
  GenerationJobCreate,
  GenerationJobList,
  JobListParams,
  PlatformGenaiSettings,
  ReplicateConnectionTest,
  ReplicateSettings,
  ReplicateSettingsUpdate,
  ReplicateUsage,
} from '@/types/genai'

const BASE = '/api/v1/genai'
const SETTINGS = '/api/v1/settings/replicate'

export const genaiApi = {
  capabilities: () => apiClient.get<CapabilitiesResponse>(`${BASE}/capabilities`),

  estimate: (data: GenerationJobCreate) =>
    apiClient.post<EstimateResponse>(`${BASE}/estimate`, data),

  createJob: (data: GenerationJobCreate) => apiClient.post<GenerationJob>(`${BASE}/jobs`, data),

  listJobs: (params: JobListParams = {}) =>
    apiClient.get<GenerationJobList>(`${BASE}/jobs`, { params }),

  getJob: (jobId: string) => apiClient.get<GenerationJob>(`${BASE}/jobs/${jobId}`),

  cancelJob: (jobId: string) => apiClient.post<GenerationJob>(`${BASE}/jobs/${jobId}/cancel`),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<GenAIAsset>(`${BASE}/uploads`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },

  adopt: (assetId: string, data: AdoptRequest) =>
    apiClient.post<AdoptResponse>(`${BASE}/assets/${assetId}/adopt`, data),

  /** Path of a stored file; fetch it with `getBlob` (files are never public). */
  assetFilePath: (assetId: string, variant: 'full' | 'thumb' = 'full') =>
    `${BASE}/assets/${assetId}/file${variant === 'thumb' ? '?variant=thumb' : ''}`,

  getBlob: (path: string) => apiClient.get<Blob>(path, { responseType: 'blob' }),

  getSettings: () => apiClient.get<ReplicateSettings>(SETTINGS),

  updateSettings: (data: ReplicateSettingsUpdate) =>
    apiClient.put<ReplicateSettings>(SETTINGS, data),

  testConnection: () => apiClient.post<ReplicateConnectionTest>(`${SETTINGS}/test`),

  usage: (months = 6) => apiClient.get<ReplicateUsage>(`${SETTINGS}/usage`, { params: { months } }),

  getPlatform: (tenantId: string) =>
    apiClient.get<PlatformGenaiSettings>(`/api/v1/platform/tenants/${tenantId}/genai`),

  setPlatform: (tenantId: string, allowed: boolean) =>
    apiClient.put<PlatformGenaiSettings>(`/api/v1/platform/tenants/${tenantId}/genai`, {
      platform_token_allowed: allowed,
    }),
}
