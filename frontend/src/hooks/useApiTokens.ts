/**
 * TanStack Query hooks for personal API tokens (spec 010).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiTokensApi } from '@/lib/api/apiTokens'
import type { ApiTokenCreateInput } from '@/types/apiToken'

export const apiTokensKey = ['api-tokens'] as const

export function useApiTokens() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: apiTokensKey, queryFn: apiTokensApi.list })

  const create = useMutation({
    mutationFn: (input: ApiTokenCreateInput) => apiTokensApi.create(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: apiTokensKey }),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => apiTokensApi.revoke(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: apiTokensKey }),
  })

  return {
    tokens: query.data?.items ?? [],
    isLoading: query.isLoading,
    error: query.error,
    createToken: create.mutateAsync,
    isCreating: create.isPending,
    revokeToken: revoke.mutateAsync,
    isRevoking: revoke.isPending,
  }
}
