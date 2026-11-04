/**
 * Model file versions with TanStack Query (spec 004, T030).
 *
 * Activating a version or changing its print file can move a model's print
 * time, parts per plate, weight and dimensions, every one an input to its cost,
 * so those mutations drop every cached cost along with the files.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import {
  activateFileVersion,
  createFileVersion,
  getActivationPreview,
  listFileVersions,
  updateFileVersion,
} from '@/lib/api/modelFileVersions'
import { anyMeasurementPending } from '@/lib/packaging'
import type { ActivationField, FileVersion } from '@/types/model-file-version'

const MEASUREMENT_POLL_MS = 5000

export const fileVersionKeys = {
  list: (modelId: string) => ['model-file-versions', modelId] as const,
  preview: (modelId: string, versionId: string, printFileId?: string) =>
    ['model-file-versions', modelId, versionId, 'preview', printFileId ?? null] as const,
}

/** Everything a version change can make stale. */
export function invalidateAfterFileChange(queryClient: QueryClient, modelId: string) {
  queryClient.invalidateQueries({ queryKey: ['model-file-versions', modelId] })
  queryClient.invalidateQueries({ queryKey: ['model-files', modelId] })
  queryClient.invalidateQueries({ queryKey: ['model-file-notes', modelId] })
  queryClient.invalidateQueries({ queryKey: ['model', modelId] })
}

function invalidateCosts(queryClient: QueryClient, modelId: string) {
  invalidateAfterFileChange(queryClient, modelId)
  queryClient.invalidateQueries({ queryKey: ['pricing'] })
  queryClient.invalidateQueries({ queryKey: ['models'] })
  queryClient.invalidateQueries({ queryKey: ['products'] })
}

export function useFileVersions(modelId: string) {
  const query = useQuery<FileVersion[]>({
    queryKey: fileVersionKeys.list(modelId),
    queryFn: () => listFileVersions(modelId),
    // A large file is measured after upload; poll until its size arrives.
    refetchInterval: (q) =>
      anyMeasurementPending((q.state.data ?? []).flatMap((v) => v.files)) ? MEASUREMENT_POLL_MS : false,
  })
  return {
    versions: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  }
}

export function useCreateFileVersion(modelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: { label?: string; note?: string }) => createFileVersion(modelId, data),
    onSuccess: () => invalidateAfterFileChange(queryClient, modelId),
  })
}

export function useUpdateFileVersion(modelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      versionId,
      ...data
    }: {
      versionId: string
      label?: string
      note?: string | null
      print_file_id?: string
    }) => updateFileVersion(modelId, versionId, data),
    onSuccess: () => invalidateAfterFileChange(queryClient, modelId),
  })
}

export function useActivationPreview(
  modelId: string,
  versionId: string | null,
  printFileId?: string
) {
  const query = useQuery({
    queryKey: fileVersionKeys.preview(modelId, versionId ?? '', printFileId),
    queryFn: () => getActivationPreview(modelId, versionId as string, printFileId),
    enabled: Boolean(versionId),
    // A preview is a comparison with the figures in force now: never reuse an old one.
    staleTime: 0,
    gcTime: 0,
  })
  return { preview: query.data, isLoading: query.isLoading, error: query.error }
}

export function useActivateFileVersion(modelId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      versionId,
      apply,
      printFileId,
    }: {
      versionId: string
      apply: ActivationField[]
      printFileId?: string
    }) => activateFileVersion(modelId, versionId, apply, printFileId),
    onSuccess: () => invalidateCosts(queryClient, modelId),
  })
}
