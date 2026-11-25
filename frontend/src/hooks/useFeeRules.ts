/**
 * Fee rule, reconciliation and margin hooks (task T085).
 *
 * A margin is derived, never stored (Constitution V), so there is no
 * optimistic margin anywhere here: showing a predicted percentage would be
 * showing one nothing computed.
 *
 * Writing a fee rule invalidates every margin, not just the one on screen. A
 * rule reaches every product priced on that channel, and a stale margin beside
 * a changed rule is the kind of figure an operator stops trusting entirely.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { feeRulesApi } from '@/lib/api/feeRules'
import type {
  ChannelPnL,
  FeeActual,
  FeeActualCreate,
  FeePreviewRequest,
  FeePreviewResponse,
  FeeRule,
  FeeRuleCreate,
  FeeRuleListResponse,
  FeeRuleUpdate,
  ProductMargin,
  ShippingProfile,
  ShippingProfileCreate,
  ShippingProfileListResponse,
  ShippingProfileUpdate,
} from '@/types/pricing'

export const feeKeys = {
  rules: (channelId: string, asOf?: string) =>
    ['fees', 'rules', channelId, asOf ?? 'all'] as const,
  preview: (channelId: string) => ['fees', 'preview', channelId] as const,
  margin: (productId: string, channelId: string, asOf?: string, quantity?: number) =>
    ['fees', 'margin', productId, channelId, asOf ?? 'current', quantity ?? 1] as const,
  channelPnl: (channelId: string, periodStart: string, periodEnd: string) =>
    ['fees', 'channel-pnl', channelId, periodStart, periodEnd] as const,
  shippingProfiles: (zone?: string) =>
    ['fees', 'shipping-profiles', zone ?? 'all'] as const,
}

/** Every margin on this channel, and the fee stack behind them. */
function invalidateChannel(
  queryClient: ReturnType<typeof useQueryClient>,
  channelId: string,
): void {
  queryClient.invalidateQueries({ queryKey: ['fees', 'rules', channelId] })
  queryClient.invalidateQueries({ queryKey: ['fees', 'margin'] })
  queryClient.invalidateQueries({ queryKey: ['fees', 'channel-pnl', channelId] })
}

/** A channel's fee rules, in `sort_order`. */
export function useFeeRules(channelId: string | undefined, asOf?: string) {
  const query = useQuery<FeeRuleListResponse>({
    queryKey: feeKeys.rules(channelId ?? '', asOf),
    queryFn: () => feeRulesApi.list(channelId as string, asOf),
    enabled: Boolean(channelId),
  })

  return {
    rules: query.data?.rules ?? [],
    total: query.data?.total ?? 0,
    asOf: query.data?.as_of,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/** Add a fee rule. Requires admin or owner. */
export function useCreateFeeRule(channelId: string) {
  const queryClient = useQueryClient()

  return useMutation<FeeRule, Error, FeeRuleCreate>({
    mutationFn: (data) => feeRulesApi.create(channelId, data),
    onSuccess: () => invalidateChannel(queryClient, channelId),
  })
}

/** Change a fee rule. Requires admin or owner. */
export function useUpdateFeeRule(channelId: string) {
  const queryClient = useQueryClient()

  return useMutation<FeeRule, Error, { ruleId: string; data: FeeRuleUpdate }>({
    mutationFn: ({ ruleId, data }) => feeRulesApi.update(channelId, ruleId, data),
    onSuccess: () => invalidateChannel(queryClient, channelId),
  })
}

/** Remove a fee rule. Requires admin or owner. */
export function useDeleteFeeRule(channelId: string) {
  const queryClient = useQueryClient()

  return useMutation<void, Error, string>({
    mutationFn: (ruleId) => feeRulesApi.remove(channelId, ruleId),
    onSuccess: () => invalidateChannel(queryClient, channelId),
  })
}

/**
 * What a hypothetical order would be charged.
 *
 * A mutation rather than a query despite creating nothing: it takes a body the
 * operator is editing, and caching a preview by its inputs would mean a stale
 * answer the moment they changed one.
 */
export function useFeePreview(channelId: string) {
  return useMutation<FeePreviewResponse, Error, FeePreviewRequest>({
    mutationFn: (order) => feeRulesApi.preview(channelId, order),
  })
}

/** What one unit earns on one channel at the price in effect. */
export function useProductMargin(
  productId: string | undefined,
  channelId: string | undefined,
  params?: { asOf?: string; quantity?: number },
) {
  const query = useQuery<ProductMargin>({
    queryKey: feeKeys.margin(
      productId ?? '',
      channelId ?? '',
      params?.asOf,
      params?.quantity,
    ),
    queryFn: () => feeRulesApi.getMargin(productId as string, channelId as string, params),
    enabled: Boolean(productId && channelId),
  })

  return {
    margin: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/** One channel over one period. */
export function useChannelPnL(params: {
  channelId: string | undefined
  periodStart: string | undefined
  periodEnd: string | undefined
}) {
  const ready = Boolean(params.channelId && params.periodStart && params.periodEnd)
  const query = useQuery<ChannelPnL>({
    queryKey: feeKeys.channelPnl(
      params.channelId ?? '',
      params.periodStart ?? '',
      params.periodEnd ?? '',
    ),
    queryFn: () =>
      feeRulesApi.getChannelPnL({
        channelId: params.channelId as string,
        periodStart: params.periodStart as string,
        periodEnd: params.periodEnd as string,
      }),
    enabled: ready,
  })

  return {
    pnl: query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/** Record what a statement charged. Requires admin or owner. */
export function useRecordFeeActual() {
  const queryClient = useQueryClient()

  return useMutation<FeeActual, Error, FeeActualCreate>({
    mutationFn: (data) => feeRulesApi.recordFeeActual(data),
    onSuccess: (_actual, variables) => {
      queryClient.invalidateQueries({
        queryKey: ['fees', 'channel-pnl', variables.sales_channel_id],
      })
    },
  })
}

/** Postage the operator pays, by zone and weight bracket. */
export function useShippingProfiles(destinationZone?: string) {
  const query = useQuery<ShippingProfileListResponse>({
    queryKey: feeKeys.shippingProfiles(destinationZone),
    queryFn: () => feeRulesApi.listShippingProfiles(destinationZone),
  })

  return {
    profiles: query.data?.profiles ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  }
}

/** Postage reaches every margin, so writing one invalidates them all. */
function invalidateShipping(queryClient: ReturnType<typeof useQueryClient>): void {
  queryClient.invalidateQueries({ queryKey: ['fees', 'shipping-profiles'] })
  queryClient.invalidateQueries({ queryKey: ['fees', 'margin'] })
}

export function useCreateShippingProfile() {
  const queryClient = useQueryClient()

  return useMutation<ShippingProfile, Error, ShippingProfileCreate>({
    mutationFn: (data) => feeRulesApi.createShippingProfile(data),
    onSuccess: () => invalidateShipping(queryClient),
  })
}

export function useUpdateShippingProfile() {
  const queryClient = useQueryClient()

  return useMutation<
    ShippingProfile,
    Error,
    { profileId: string; data: ShippingProfileUpdate }
  >({
    mutationFn: ({ profileId, data }) =>
      feeRulesApi.updateShippingProfile(profileId, data),
    onSuccess: () => invalidateShipping(queryClient),
  })
}

export function useDeleteShippingProfile() {
  const queryClient = useQueryClient()

  return useMutation<void, Error, string>({
    mutationFn: (profileId) => feeRulesApi.deleteShippingProfile(profileId),
    onSuccess: () => invalidateShipping(queryClient),
  })
}
