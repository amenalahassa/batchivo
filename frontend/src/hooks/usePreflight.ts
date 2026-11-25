/**
 * Preflight foundations with TanStack Query (spec 009): design briefs, fit
 * calibrations and print test results.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  calibrationsApi,
  designBriefsApi,
  printTestResultsApi,
  type BriefOwner,
} from '@/lib/api/preflight'
import type {
  CalibrationCreate,
  DesignBrief,
  DesignBriefStart,
  DesignBriefUpdate,
  PrintTestResultCreate,
  PrintTestResultParams,
  PrintTestResultUpdate,
  RevisionPart,
} from '@/types/preflight'

export const preflightKeys = {
  brief: (owner: BriefOwner) => ['design-brief', owner] as const,
  revisions: (briefId: string, part?: RevisionPart) =>
    ['design-brief-revisions', briefId, part ?? 'all'] as const,
  calibrations: (printerId: string) => ['calibrations', printerId] as const,
  testResults: (params: PrintTestResultParams) => ['print-test-results', params] as const,
}

// ============================================
// Design briefs
// ============================================

export function useDesignBrief(owner: BriefOwner) {
  const query = useQuery({
    queryKey: preflightKeys.brief(owner),
    queryFn: () => designBriefsApi.getFor(owner),
  })
  return { brief: query.data ?? null, isLoading: query.isLoading, error: query.error }
}

function useBriefChanged() {
  const queryClient = useQueryClient()
  return (brief: DesignBrief) => {
    // A brief is reached from its idea and from its model: refresh both.
    queryClient.invalidateQueries({ queryKey: ['design-brief'] })
    queryClient.invalidateQueries({ queryKey: ['design-brief-revisions', brief.id] })
  }
}

export function useStartDesignBrief(owner: BriefOwner) {
  const changed = useBriefChanged()
  return useMutation({
    mutationFn: (data: DesignBriefStart = {}) => designBriefsApi.start(owner, data),
    onSuccess: changed,
  })
}

export function useUpdateDesignBrief(briefId: string) {
  const changed = useBriefChanged()
  return useMutation({
    mutationFn: (data: DesignBriefUpdate) => designBriefsApi.update(briefId, data),
    onSuccess: changed,
  })
}

export function useBriefRevisions(briefId: string, part: RevisionPart | undefined, enabled = true) {
  const query = useQuery({
    queryKey: preflightKeys.revisions(briefId, part),
    queryFn: () => designBriefsApi.revisions(briefId, part),
    enabled,
  })
  return { revisions: query.data ?? [], isLoading: query.isLoading, error: query.error }
}

// ============================================
// Calibrations
// ============================================

export function useCalibrations(printerId: string, enabled = true) {
  const query = useQuery({
    queryKey: preflightKeys.calibrations(printerId),
    queryFn: () => calibrationsApi.listForPrinter(printerId),
    enabled,
  })
  return { calibrations: query.data ?? [], isLoading: query.isLoading, error: query.error }
}

export function useRecordCalibration(printerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: CalibrationCreate) => calibrationsApi.record(printerId, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calibrations', printerId] }),
  })
}

// ============================================
// Print test results
// ============================================

export function usePrintTestResults(params: PrintTestResultParams, enabled = true) {
  const query = useQuery({
    queryKey: preflightKeys.testResults(params),
    queryFn: () => printTestResultsApi.list(params),
    enabled,
  })
  return {
    results: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
  }
}

function useResultsChanged() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['print-test-results'] })
}

export function useRecordTestResult() {
  const changed = useResultsChanged()
  return useMutation({
    mutationFn: async ({ photo, ...data }: PrintTestResultCreate & { photo?: File | null }) => {
      const result = await printTestResultsApi.create(data)
      return photo ? printTestResultsApi.uploadPhoto(result.id, photo) : result
    },
    onSuccess: changed,
  })
}

export function useUpdateTestResult() {
  const changed = useResultsChanged()
  return useMutation({
    mutationFn: ({ resultId, ...data }: PrintTestResultUpdate & { resultId: string }) =>
      printTestResultsApi.update(resultId, data),
    onSuccess: changed,
  })
}
