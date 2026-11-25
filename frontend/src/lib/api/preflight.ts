/**
 * Preflight foundations API (spec 009, contracts/api.md): design briefs, fit
 * calibrations and print test results.
 */
import { apiClient } from '@/lib/api'
import { apiErrorStatus } from '@/lib/apiError'
import type {
  Calibration,
  CalibrationCreate,
  DesignBrief,
  DesignBriefRevision,
  DesignBriefStart,
  DesignBriefUpdate,
  DesignBriefUpdateResult,
  PrintTestResult,
  PrintTestResultCreate,
  PrintTestResultList,
  PrintTestResultParams,
  PrintTestResultUpdate,
  RevisionPart,
} from '@/types/preflight'

const V1 = '/api/v1'

/** Whose brief: an idea or a model (a model also reaches its source idea's brief). */
export type BriefOwner = { ideaId: string } | { modelId: string }

function ownerPath(owner: BriefOwner): string {
  return 'ideaId' in owner
    ? `${V1}/ideas/${owner.ideaId}/design-brief`
    : `${V1}/models/${owner.modelId}/design-brief`
}

export const designBriefsApi = {
  /** The owner's brief, or null when it has none yet (404 "No design brief yet"). */
  getFor: async (owner: BriefOwner): Promise<DesignBrief | null> => {
    try {
      return await apiClient.get<DesignBrief>(ownerPath(owner))
    } catch (error) {
      if (apiErrorStatus(error) === 404) return null
      throw error
    }
  },

  start: (owner: BriefOwner, data: DesignBriefStart = {}) =>
    apiClient.post<DesignBrief>(ownerPath(owner), data),

  get: (briefId: string) => apiClient.get<DesignBrief>(`${V1}/design-briefs/${briefId}`),

  update: (briefId: string, data: DesignBriefUpdate) =>
    apiClient.patch<DesignBriefUpdateResult>(`${V1}/design-briefs/${briefId}`, data),

  revisions: (briefId: string, part?: RevisionPart) =>
    apiClient.get<DesignBriefRevision[]>(`${V1}/design-briefs/${briefId}/revisions`, {
      params: part ? { part } : undefined,
    }),
}

export const calibrationsApi = {
  listForPrinter: (printerId: string, currentOnly = false) =>
    apiClient.get<Calibration[]>(`${V1}/printers/${printerId}/calibrations`, {
      params: currentOnly ? { current_only: true } : undefined,
    }),

  record: (printerId: string, data: CalibrationCreate) =>
    apiClient.post<Calibration>(`${V1}/printers/${printerId}/calibrations`, data),
}

export const printTestResultsApi = {
  list: (params: PrintTestResultParams) =>
    apiClient.get<PrintTestResultList>(`${V1}/print-test-results`, { params }),

  create: (data: PrintTestResultCreate) =>
    apiClient.post<PrintTestResult>(`${V1}/print-test-results`, data),

  update: (resultId: string, data: PrintTestResultUpdate) =>
    apiClient.patch<PrintTestResult>(`${V1}/print-test-results/${resultId}`, data),

  uploadPhoto: (resultId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<PrintTestResult>(`${V1}/print-test-results/${resultId}/photo`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },

  /** Path of the private photo, for `AuthImage` (fetched with the session). */
  photoPath: (result: PrintTestResult, variant: 'full' | 'thumb' = 'thumb') =>
    result.photo_available
      ? `${V1}/print-test-results/${result.id}/photo?variant=${variant}&v=${encodeURIComponent(result.updated_at)}`
      : null,
}
