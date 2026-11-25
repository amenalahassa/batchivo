/**
 * API client for personal API tokens (spec 010).
 */

import { api } from '../api'
import type {
  ApiToken,
  ApiTokenCreated,
  ApiTokenCreateInput,
  ApiTokenListResponse,
} from '@/types/apiToken'

const BASE = '/api/v1/api-tokens'

export const apiTokensApi = {
  async list(): Promise<ApiTokenListResponse> {
    const response = await api.get<ApiTokenListResponse>(BASE)
    return response.data
  },

  async create(input: ApiTokenCreateInput): Promise<ApiTokenCreated> {
    const response = await api.post<ApiTokenCreated>(BASE, input)
    return response.data
  },

  async revoke(id: string): Promise<ApiToken> {
    const response = await api.post<ApiToken>(`${BASE}/${id}/revoke`)
    return response.data
  },
}
