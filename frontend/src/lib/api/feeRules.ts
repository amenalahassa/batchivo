import { apiClient } from '../api'
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
  MarginDivergenceList,
  ProductMargin,
  ShippingProfile,
  ShippingProfileCreate,
  ShippingProfileListResponse,
  ShippingProfileUpdate,
} from '@/types/pricing'

/**
 * Fee rules, shipping profiles, reconciliation and margin (task T085).
 *
 * Every money and percentage field in these payloads is a decimal **string**
 * and stays one: nothing here parses an amount into a number
 * (Constitution IV). Components render the string or hand it to `lib/money`.
 */
export const feeRulesApi = {
  /**
   * A channel's fee rules.
   *
   * Without `asOf` every rule comes back, closed ones included: reconciling a
   * statement from March needs March's rule as well as today's.
   */
  list: async (channelId: string, asOf?: string): Promise<FeeRuleListResponse> => {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
    return apiClient.get<FeeRuleListResponse>(
      `/api/v1/sales-channels/${channelId}/fee-rules${query}`,
    )
  },

  /** Add a fee rule. Requires admin or owner (FR-007a). */
  create: async (channelId: string, data: FeeRuleCreate): Promise<FeeRule> => {
    return apiClient.post<FeeRule>(`/api/v1/sales-channels/${channelId}/fee-rules`, data)
  },

  /** Change a fee rule. Fields left out are not touched. */
  update: async (
    channelId: string,
    ruleId: string,
    data: FeeRuleUpdate,
  ): Promise<FeeRule> => {
    return apiClient.put<FeeRule>(
      `/api/v1/sales-channels/${channelId}/fee-rules/${ruleId}`,
      data,
    )
  },

  /**
   * Remove a fee rule.
   *
   * A rule the channel has stopped charging is better closed with `applies_to`
   * than deleted: closing it keeps a past order's fees explainable.
   */
  remove: async (channelId: string, ruleId: string): Promise<void> => {
    return apiClient.delete<void>(
      `/api/v1/sales-channels/${channelId}/fee-rules/${ruleId}`,
    )
  },

  /**
   * What a hypothetical order would be charged. Creates nothing.
   *
   * This is the fee engine made inspectable, which is how an operator checks a
   * rule before believing a margin built on it (FR-018).
   */
  preview: async (
    channelId: string,
    order: FeePreviewRequest,
  ): Promise<FeePreviewResponse> => {
    return apiClient.post<FeePreviewResponse>(
      `/api/v1/sales-channels/${channelId}/fee-rules/preview`,
      order,
    )
  },

  /** What one unit earns on one channel at the price in effect. */
  getMargin: async (
    productId: string,
    channelId: string,
    params?: { asOf?: string; quantity?: number },
  ): Promise<ProductMargin> => {
    const query = new URLSearchParams()
    if (params?.asOf) query.append('as_of', params.asOf)
    if (params?.quantity !== undefined) query.append('quantity', params.quantity.toString())
    const queryString = query.toString()
    return apiClient.get<ProductMargin>(
      `/api/v1/products/${productId}/pricing/${channelId}/margin${
        queryString ? `?${queryString}` : ''
      }`,
    )
  },

  /** Record what a statement charged. Requires admin or owner (FR-007a). */
  recordFeeActual: async (data: FeeActualCreate): Promise<FeeActual> => {
    return apiClient.post<FeeActual>('/api/v1/reconciliation/fee-actuals', data)
  },

  /** One channel over one period: revenue, fees, absorption and margin. */
  getChannelPnL: async (params: {
    channelId: string
    periodStart: string
    periodEnd: string
  }): Promise<ChannelPnL> => {
    const query = new URLSearchParams({
      channel_id: params.channelId,
      period_start: params.periodStart,
      period_end: params.periodEnd,
    })
    return apiClient.get<ChannelPnL>(`/api/v1/reconciliation/channel-pnl?${query.toString()}`)
  },

  /**
   * What settled lines actually earned, against the margin they were sold at.
   *
   * This is the in-app half of the FR-042 alert. The sweep in
   * `app/tasks/margin_alerts.py` emails the operator; this is what they open
   * when they get the email, and what the console shows without one. Passing
   * `onlyAlerting` narrows it to the lines past their own threshold -- the
   * ones FR-042 says they must be alerted about.
   *
   * Open to every role (FR-007c): the threshold is monetary policy, but
   * reading its consequence is not.
   */
  getMarginDivergence: async (params?: {
    productId?: string
    since?: string
    onlyAlerting?: boolean
    limit?: number
  }): Promise<MarginDivergenceList> => {
    const query = new URLSearchParams()
    if (params?.productId) query.append('product_id', params.productId)
    if (params?.since) query.append('since', params.since)
    if (params?.onlyAlerting) query.append('only_alerting', 'true')
    if (params?.limit !== undefined) query.append('limit', params.limit.toString())
    const queryString = query.toString()
    return apiClient.get<MarginDivergenceList>(
      `/api/v1/reconciliation/margin-divergence${queryString ? `?${queryString}` : ''}`,
    )
  },

  listShippingProfiles: async (
    destinationZone?: string,
  ): Promise<ShippingProfileListResponse> => {
    const query = destinationZone
      ? `?destination_zone=${encodeURIComponent(destinationZone)}`
      : ''
    return apiClient.get<ShippingProfileListResponse>(`/api/v1/shipping-profiles${query}`)
  },

  createShippingProfile: async (data: ShippingProfileCreate): Promise<ShippingProfile> => {
    return apiClient.post<ShippingProfile>('/api/v1/shipping-profiles', data)
  },

  updateShippingProfile: async (
    profileId: string,
    data: ShippingProfileUpdate,
  ): Promise<ShippingProfile> => {
    return apiClient.put<ShippingProfile>(`/api/v1/shipping-profiles/${profileId}`, data)
  },

  deleteShippingProfile: async (profileId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/shipping-profiles/${profileId}`)
  },
}
