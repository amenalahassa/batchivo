/**
 * Product ideas API (spec 007, contracts/ideas-api.md).
 */
import { apiClient } from '@/lib/api'
import type {
  ConvertRequest,
  ConvertResponse,
  IdeaCreate,
  IdeaDetail,
  IdeaEntry,
  IdeaEntryCreate,
  IdeaEntryList,
  IdeaEntryUpdate,
  IdeaListParams,
  IdeaListResponse,
  IdeaUpdate,
  ImageEntryKind,
  ImageUploadResult,
  ImportItem,
  ImportResult,
  ParseReportResponse,
} from '@/types/idea'

const BASE = '/api/v1/ideas'

/** Repeat array params as `status=a&status=b`, as FastAPI expects. */
function listQuery(params: IdeaListParams = {}): URLSearchParams {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => query.append(key, String(v)))
    else query.append(key, String(value))
  }
  return query
}

export const ideasApi = {
  list: (params?: IdeaListParams) =>
    apiClient.get<IdeaListResponse>(BASE, { params: listQuery(params) }),

  tags: () => apiClient.get<string[]>(`${BASE}/tags`),

  get: (ideaId: string) => apiClient.get<IdeaDetail>(`${BASE}/${ideaId}`),

  create: (data: IdeaCreate) => apiClient.post<IdeaDetail>(BASE, data),

  update: (ideaId: string, data: IdeaUpdate) =>
    apiClient.patch<IdeaDetail>(`${BASE}/${ideaId}`, data),

  archive: (ideaId: string) => apiClient.delete<IdeaDetail>(`${BASE}/${ideaId}`),

  restore: (ideaId: string) =>
    apiClient.patch<IdeaDetail>(`${BASE}/${ideaId}`, { archived: false }),

  listEntries: (ideaId: string, includeArchived = false) =>
    apiClient.get<IdeaEntryList>(`${BASE}/${ideaId}/entries`, {
      params: includeArchived ? { archived: true } : undefined,
    }),

  createEntry: (ideaId: string, data: IdeaEntryCreate) =>
    apiClient.post<IdeaEntry>(`${BASE}/${ideaId}/entries`, data),

  uploadImages: (ideaId: string, files: File[], kind: ImageEntryKind = 'image') => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    form.append('kind', kind)
    return apiClient.post<ImageUploadResult>(`${BASE}/${ideaId}/entries/images`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },

  updateEntry: (ideaId: string, entryId: string, data: IdeaEntryUpdate) =>
    apiClient.patch<IdeaEntry>(`${BASE}/${ideaId}/entries/${entryId}`, data),

  archiveEntry: (ideaId: string, entryId: string) =>
    apiClient.delete<IdeaEntry>(`${BASE}/${ideaId}/entries/${entryId}`),

  startIteration: (ideaId: string, note?: string) =>
    apiClient.post<IdeaEntryList>(`${BASE}/${ideaId}/iterations`, { note: note || null }),

  convert: (ideaId: string, data: ConvertRequest) =>
    apiClient.post<ConvertResponse>(`${BASE}/${ideaId}/convert`, data),

  importItems: (items: ImportItem[], dryRun = false) =>
    apiClient.post<ImportResult>(`${BASE}/import`, { items, dry_run: dryRun }),

  parseReport: (text: string) =>
    apiClient.post<ParseReportResponse>(`${BASE}/import/parse-report`, { text }),

  /** An idea image, fetched with the operator's session (images are never public). */
  getImageBlob: (path: string) => apiClient.get<Blob>(path, { responseType: 'blob' }),
}
