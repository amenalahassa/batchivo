/**
 * Personal API tokens (spec 010) — mirrors backend/app/schemas/api_token.py.
 */

export type ApiTokenScope = 'read' | 'write' | 'genai' | 'print'
export type ApiTokenStatus = 'active' | 'expired' | 'revoked'

export interface ApiToken {
  id: string
  name: string
  token_prefix: string
  scopes: ApiTokenScope[]
  created_at: string
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
  status: ApiTokenStatus
}

/** The creation response: the only place the secret appears. */
export interface ApiTokenCreated extends ApiToken {
  token: string
}

export interface ApiTokenListResponse {
  items: ApiToken[]
  total: number
}

export interface ApiTokenCreateInput {
  name: string
  scopes: ApiTokenScope[]
  /** ISO datetime with time zone, at most one year ahead. */
  expires_at: string
}
