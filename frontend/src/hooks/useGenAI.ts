/**
 * Generative AI with TanStack Query (spec 008).
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'

import { genaiApi } from '@/lib/api/genai'
import type {
  AdoptRequest,
  GenAIErrorDetail,
  GenerationJob,
  GenerationJobCreate,
  JobListParams,
  ReplicateSettingsUpdate,
} from '@/types/genai'

export const genaiKeys = {
  all: ['genai'] as const,
  capabilities: () => ['genai', 'capabilities'] as const,
  settings: () => ['genai', 'settings'] as const,
  usage: (months: number) => ['genai', 'usage', months] as const,
  platform: (tenantId: string) => ['genai', 'platform', tenantId] as const,
  jobs: (params: JobListParams) => ['genai', 'jobs', params] as const,
  job: (jobId: string) => ['genai', 'job', jobId] as const,
  estimate: (req: GenerationJobCreate | null) => ['genai', 'estimate', req] as const,
  blob: (path: string | null | undefined) => ['genai', 'blob', path] as const,
}

/** The `{code, message}` of a refused request, or a generic one. */
export function genaiError(error: unknown): GenAIErrorDetail | null {
  if (!error) return null
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      return detail as GenAIErrorDetail
    }
    if (typeof detail === 'string') return { code: 'error', message: detail }
    if (Array.isArray(detail) && detail[0]?.msg) {
      return { code: 'invalid_input', message: String(detail[0].msg) }
    }
  }
  return { code: 'error', message: 'Something went wrong. Try again.' }
}

const isActive = (job: GenerationJob | undefined) =>
  job?.status === 'queued' || job?.status === 'running'

// ---------------------------------------------------------------------- capabilities & settings

export function useCapabilities(enabled = true) {
  const query = useQuery({
    queryKey: genaiKeys.capabilities(),
    queryFn: genaiApi.capabilities,
    enabled,
    staleTime: 60_000,
  })
  return {
    capabilities: query.data?.capabilities ?? [],
    connected: query.data?.connected ?? false,
    tokenSource: query.data?.token_source ?? 'none',
    isLoading: query.isLoading,
    error: query.error,
  }
}

export function useReplicateSettings(enabled = true) {
  const query = useQuery({
    queryKey: genaiKeys.settings(),
    queryFn: genaiApi.getSettings,
    enabled,
  })
  return { settings: query.data, isLoading: query.isLoading, error: query.error }
}

export function useUpdateReplicateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ReplicateSettingsUpdate) => genaiApi.updateSettings(data),
    onSuccess: (settings) => {
      queryClient.setQueryData(genaiKeys.settings(), settings)
      queryClient.invalidateQueries({ queryKey: genaiKeys.capabilities() })
    },
  })
}

export function useTestReplicate() {
  return useMutation({ mutationFn: () => genaiApi.testConnection() })
}

export function useReplicateUsage(months = 6, enabled = true) {
  const query = useQuery({
    queryKey: genaiKeys.usage(months),
    queryFn: () => genaiApi.usage(months),
    enabled,
  })
  return { months: query.data?.months ?? [], isLoading: query.isLoading }
}

export function usePlatformGenai(tenantId: string) {
  const query = useQuery({
    queryKey: genaiKeys.platform(tenantId),
    queryFn: () => genaiApi.getPlatform(tenantId),
    enabled: Boolean(tenantId),
  })
  return { platform: query.data, isLoading: query.isLoading, error: query.error }
}

export function useSetPlatformGenai(tenantId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (allowed: boolean) => genaiApi.setPlatform(tenantId, allowed),
    onSuccess: (data) => queryClient.setQueryData(genaiKeys.platform(tenantId), data),
  })
}

// ---------------------------------------------------------------------- jobs

export function useGenerationJob(jobId: string | null | undefined) {
  const query = useQuery({
    queryKey: genaiKeys.job(jobId ?? ''),
    queryFn: () => genaiApi.getJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (q) => (isActive(q.state.data) ? 2000 : false),
  })
  return { job: query.data, isLoading: query.isLoading, error: query.error }
}

export function useGenerationJobs(params: JobListParams, enabled = true) {
  const query = useQuery({
    queryKey: genaiKeys.jobs(params),
    queryFn: () => genaiApi.listJobs(params),
    enabled,
    refetchInterval: (q) => (q.state.data?.items.some(isActive) ? 4000 : false),
  })
  return {
    jobs: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
  }
}

export function useCreateJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: GenerationJobCreate) => genaiApi.createJob(data),
    onSuccess: (job) => {
      queryClient.setQueryData(genaiKeys.job(job.id), job)
      queryClient.invalidateQueries({ queryKey: ['genai', 'jobs'] })
      queryClient.invalidateQueries({ queryKey: genaiKeys.settings() })
    },
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => genaiApi.cancelJob(jobId),
    onSuccess: (job) => {
      queryClient.setQueryData(genaiKeys.job(job.id), job)
      queryClient.invalidateQueries({ queryKey: ['genai', 'jobs'] })
    },
  })
}

/** Invalidate what an adoption changed on its target. */
export function invalidateAdoptionTarget(
  queryClient: ReturnType<typeof useQueryClient>,
  target: AdoptRequest['target']
) {
  const id = target.id ?? ''
  if (target.type === 'idea') {
    queryClient.invalidateQueries({ queryKey: ['ideas'] })
  } else if (target.type === 'product') {
    queryClient.invalidateQueries({ queryKey: ['product-images', id] })
    queryClient.invalidateQueries({ queryKey: ['product', id] })
  } else if (target.type === 'model') {
    queryClient.invalidateQueries({ queryKey: ['model-files', id] })
    queryClient.invalidateQueries({ queryKey: ['model-file-versions', id] })
    queryClient.invalidateQueries({ queryKey: ['model', id] })
  }
}

export function useAdoptAsset() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ assetId, data }: { assetId: string; data: AdoptRequest }) =>
      genaiApi.adopt(assetId, data),
    onSuccess: (_result, { data }) => {
      invalidateAdoptionTarget(queryClient, data.target)
      queryClient.invalidateQueries({ queryKey: ['genai', 'job'] })
      queryClient.invalidateQueries({ queryKey: ['genai', 'jobs'] })
    },
  })
}

export function useUploadInput() {
  return useMutation({ mutationFn: (file: File) => genaiApi.upload(file) })
}

/** A request's estimated cost, refreshed 400 ms after the request stops changing. */
export function useEstimate(request: GenerationJobCreate | null, enabled = true) {
  const [debounced, setDebounced] = useState(request)
  const serialised = JSON.stringify(request)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(request), 400)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the serialised request
  }, [serialised])
  const query = useQuery({
    queryKey: genaiKeys.estimate(debounced),
    queryFn: () => genaiApi.estimate(debounced as GenerationJobCreate),
    enabled: enabled && Boolean(debounced),
    retry: false,
    placeholderData: (previous) => previous,
  })
  return { estimate: query.data, isLoading: query.isLoading, error: query.error }
}

/** A stored genai file as a blob, loaded with the operator's session. */
export function useGenAIBlob(path: string | null | undefined) {
  const query = useQuery({
    queryKey: genaiKeys.blob(path),
    queryFn: () => genaiApi.getBlob(path as string),
    enabled: Boolean(path),
    staleTime: Infinity,
    gcTime: 10 * 60 * 1000,
    retry: false,
  })
  return { blob: query.data, isLoading: query.isLoading, isError: query.isError }
}
