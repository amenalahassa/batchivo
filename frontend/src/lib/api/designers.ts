/**
 * Designers API client
 *
 * Provides TypeScript functions for interacting with the designers API endpoints.
 * Designers are licensed creators whose designs are printed and sold.
 */

import { apiClient } from '../api'
import type { Money } from '@/types/pricing'

// ==================== Types ====================

export interface Designer {
  id: string
  name: string
  slug: string
  description?: string | null
  logo_url?: string
  website_url?: string
  social_links?: Record<string, string>
  /**
   * A decimal string, not a number.
   *
   * The backend holds this as `Numeric(10, 2)` and a `Mapped[Decimal]`. It
   * crossed the wire as a JSON number, and the edit form sent it back through
   * `parseFloat`, so whatever binary noise the double picked up went into the
   * column. A recurring operator expense is somebody's money, and
   * Constitution IV admits no exception for it (FR-047).
   */
  membership_cost?: Money
  membership_start_date?: string
  membership_renewal_date?: string
  is_active: boolean
  notes?: string
  product_count: number
  created_at: string
  updated_at: string
}

export interface DesignerListResponse {
  designers: Designer[]
  total: number
}

export interface DesignerCreateRequest {
  name: string
  slug?: string
  description?: string | null
  logo_url?: string
  website_url?: string
  social_links?: Record<string, string>
  membership_cost?: Money
  membership_start_date?: string
  membership_renewal_date?: string
  is_active?: boolean
  notes?: string
}

export interface DesignerUpdateRequest {
  name?: string
  slug?: string
  description?: string | null
  logo_url?: string | null
  website_url?: string | null
  social_links?: Record<string, string> | null
  membership_cost?: Money | null
  membership_start_date?: string | null
  membership_renewal_date?: string | null
  is_active?: boolean
  notes?: string | null
}

export interface DesignerListParams {
  page?: number
  limit?: number
  search?: string
  include_inactive?: boolean
}

// ==================== API Functions ====================

/**
 * List all designers with pagination and filtering
 */
export async function listDesigners(params?: DesignerListParams): Promise<DesignerListResponse> {
  const queryParams = new URLSearchParams()

  if (params?.page !== undefined) queryParams.append('page', params.page.toString())
  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.search) queryParams.append('search', params.search)
  if (params?.include_inactive !== undefined) queryParams.append('include_inactive', params.include_inactive.toString())

  const url = `/api/v1/designers${queryParams.toString() ? `?${queryParams.toString()}` : ''}`
  return apiClient.get<DesignerListResponse>(url)
}

/**
 * Get a single designer by ID
 */
export async function getDesigner(designerId: string): Promise<Designer> {
  return apiClient.get<Designer>(`/api/v1/designers/${designerId}`)
}

/**
 * Create a new designer
 */
export async function createDesigner(data: DesignerCreateRequest): Promise<Designer> {
  return apiClient.post<Designer>('/api/v1/designers', data)
}

/**
 * Update an existing designer
 */
export async function updateDesigner(designerId: string, data: DesignerUpdateRequest): Promise<Designer> {
  return apiClient.patch<Designer>(`/api/v1/designers/${designerId}`, data)
}

/**
 * Delete a designer
 */
export async function deleteDesigner(designerId: string): Promise<void> {
  return apiClient.delete(`/api/v1/designers/${designerId}`)
}
