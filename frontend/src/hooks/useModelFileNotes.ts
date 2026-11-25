/**
 * Notes pinned on model files with TanStack Query (spec 004, T050).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  carryFileNoteForward,
  createFileNote,
  listFileNotes,
  updateFileNote,
  type NoteListParams,
} from '@/lib/api/modelFileNotes'
import type { FileNote, NoteCreate, NoteUpdate } from '@/types/model-file-version'

export const fileNoteKeys = {
  list: (modelId: string, params?: NoteListParams) =>
    ['model-file-notes', modelId, params ?? {}] as const,
}

export function useFileNotes(modelId: string, params?: NoteListParams, enabled = true) {
  const query = useQuery<FileNote[]>({
    queryKey: fileNoteKeys.list(modelId, params),
    queryFn: () => listFileNotes(modelId, params),
    enabled,
  })
  return { notes: query.data ?? [], isLoading: query.isLoading, error: query.error }
}

function useInvalidateNotes(modelId: string) {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ['model-file-notes', modelId] })
    // The versions list carries each version's open-note count.
    queryClient.invalidateQueries({ queryKey: ['model-file-versions', modelId] })
  }
}

export function useCreateFileNote(modelId: string) {
  const invalidate = useInvalidateNotes(modelId)
  return useMutation({
    mutationFn: ({ fileId, ...data }: NoteCreate & { fileId: string }) =>
      createFileNote(modelId, fileId, data),
    onSuccess: invalidate,
  })
}

export function useUpdateFileNote(modelId: string) {
  const invalidate = useInvalidateNotes(modelId)
  return useMutation({
    mutationFn: ({ noteId, ...data }: NoteUpdate & { noteId: string }) =>
      updateFileNote(modelId, noteId, data),
    onSuccess: invalidate,
  })
}

export function useCarryFileNoteForward(modelId: string) {
  const invalidate = useInvalidateNotes(modelId)
  return useMutation({
    mutationFn: ({ noteId, targetFileId }: { noteId: string; targetFileId: string }) =>
      carryFileNoteForward(modelId, noteId, targetFileId),
    onSuccess: invalidate,
  })
}
