import { apiClient } from '../api'
import type { PrintJobStatus, ProfitabilityRanking } from '@/types/pricing'

/**
 * The print queue ranked by profit per machine-hour (task T234, FR-043).
 *
 * Read-only and open to every role: the ranking reorders nothing. Money and
 * hours stay the decimal strings the API sends (Constitution IV).
 */
export const printQueueApi = {
  profitability: async (
    params: { status?: PrintJobStatus; salesChannelId?: string; asOf?: string } = {},
  ): Promise<ProfitabilityRanking> => {
    const query = new URLSearchParams()
    if (params.status) query.set('status', params.status)
    if (params.salesChannelId) query.set('sales_channel_id', params.salesChannelId)
    if (params.asOf) query.set('as_of', params.asOf)
    const suffix = query.toString() ? `?${query}` : ''
    return apiClient.get<ProfitabilityRanking>(`/api/v1/print-queue/profitability${suffix}`)
  },
}
