/**
 * Notes pinned on model files (spec 004, contracts/api.md: Notes).
 */
import { apiClient } from '@/lib/api'
import type { FileNote, NoteCreate, NoteStatus, NoteUpdate } from '@/types/model-file-version'

export interface NoteListParams {
  file_id?: string
  version_id?: string
  status?: NoteStatus
  include_archived?: boolean
  /** Also return earlier versions' open notes, marked `ghost` (FR-029). */
  ghosts_for_file_id?: string
}

export async function listFileNotes(modelId: string, params?: NoteListParams): Promise<FileNote[]> {
  return apiClient.get<FileNote[]>(`/api/v1/models/${modelId}/file-notes`, { params })
}

export async function createFileNote(
  modelId: string,
  fileId: string,
  data: NoteCreate
): Promise<FileNote> {
  return apiClient.post<FileNote>(`/api/v1/models/${modelId}/files/${fileId}/notes`, data)
}

export async function updateFileNote(
  modelId: string,
  noteId: string,
  data: NoteUpdate
): Promise<FileNote> {
  return apiClient.patch<FileNote>(`/api/v1/models/${modelId}/file-notes/${noteId}`, data)
}

export async function carryFileNoteForward(
  modelId: string,
  noteId: string,
  targetFileId: string
): Promise<FileNote> {
  return apiClient.post<FileNote>(
    `/api/v1/models/${modelId}/file-notes/${noteId}/carry-forward`,
    { target_file_id: targetFileId }
  )
}
