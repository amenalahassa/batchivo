/**
 * Model file versions API (spec 004, contracts/api.md: Versions).
 */
import { apiClient } from '@/lib/api'
import type {
  ActivationField,
  ActivationPreview,
  FileVersion,
} from '@/types/model-file-version'

const base = (modelId: string) => `/api/v1/models/${modelId}/file-versions`

export async function listFileVersions(modelId: string): Promise<FileVersion[]> {
  return apiClient.get<FileVersion[]>(base(modelId))
}

export async function createFileVersion(
  modelId: string,
  data: { label?: string; note?: string }
): Promise<FileVersion> {
  return apiClient.post<FileVersion>(base(modelId), data)
}

export async function updateFileVersion(
  modelId: string,
  versionId: string,
  data: { label?: string; note?: string | null; print_file_id?: string }
): Promise<FileVersion> {
  return apiClient.patch<FileVersion>(`${base(modelId)}/${versionId}`, data)
}

export async function getActivationPreview(
  modelId: string,
  versionId: string,
  printFileId?: string
): Promise<ActivationPreview> {
  return apiClient.get<ActivationPreview>(`${base(modelId)}/${versionId}/activation-preview`, {
    params: printFileId ? { print_file_id: printFileId } : undefined,
  })
}

export async function activateFileVersion(
  modelId: string,
  versionId: string,
  apply: ActivationField[],
  printFileId?: string
): Promise<FileVersion> {
  return apiClient.post<FileVersion>(`${base(modelId)}/${versionId}/activate`, {
    apply,
    print_file_id: printFileId ?? null,
  })
}
