/**
 * Categories API client
 *
 * Provides TypeScript functions for interacting with the categories API endpoints.
 * Categories are used to organize products in the shop.
 */

import { apiClient } from '../api'

// ==================== Types ====================

export interface Category {
  id: string
  tenant_id: string
  name: string
  slug: string
  description?: string | null
  image_url?: string
  parent_id?: string
  display_order: number
  is_active: boolean
  product_count?: number
  created_at: string
  updated_at: string
}

export interface CategoryListResponse {
  categories: Category[]
  total: number
}

export interface CategoryCreateRequest {
  name: string
  slug?: string
  description?: string | null
  image_url?: string
  parent_id?: string
  display_order?: number
  is_active?: boolean
}

export interface CategoryUpdateRequest {
  name?: string
  slug?: string
  description?: string | null
  image_url?: string | null
  parent_id?: string | null
  display_order?: number
  is_active?: boolean
}

export interface CategoryListParams {
  skip?: number
  limit?: number
  search?: string
  parent_id?: string | null
  /** List inactive categories too (the API lists active ones only by default). */
  include_inactive?: boolean
}

// ==================== API Functions ====================

/**
 * List all categories with pagination and filtering
 */
export async function listCategories(params?: CategoryListParams): Promise<CategoryListResponse> {
  const queryParams = new URLSearchParams()

  if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString())
  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.search) queryParams.append('search', params.search)
  if (params?.parent_id !== undefined) {
    queryParams.append('parent_id', params.parent_id === null ? 'null' : params.parent_id)
  }
  if (params?.include_inactive) queryParams.append('include_inactive', 'true')

  const url = `/api/v1/categories${queryParams.toString() ? `?${queryParams.toString()}` : ''}`
  return apiClient.get<CategoryListResponse>(url)
}

/**
 * Get a single category by ID
 */
export async function getCategory(categoryId: string): Promise<Category> {
  return apiClient.get<Category>(`/api/v1/categories/${categoryId}`)
}

/**
 * Create a new category
 */
export async function createCategory(data: CategoryCreateRequest): Promise<Category> {
  return apiClient.post<Category>('/api/v1/categories', data)
}

/**
 * Update an existing category
 */
export async function updateCategory(categoryId: string, data: CategoryUpdateRequest): Promise<Category> {
  return apiClient.patch<Category>(`/api/v1/categories/${categoryId}`, data)
}

/**
 * Delete a category
 */
export async function deleteCategory(categoryId: string): Promise<void> {
  return apiClient.delete(`/api/v1/categories/${categoryId}`)
}

/**
 * Reorder categories (bulk update display_order)
 */
export async function reorderCategories(categoryOrders: { id: string; display_order: number }[]): Promise<void> {
  // Update each category's display_order
  await Promise.all(
    categoryOrders.map(({ id, display_order }) =>
      updateCategory(id, { display_order })
    )
  )
}

/**
 * The display_order updates that move one category a step up or down.
 *
 * `sorted` is the list as shown. Swapping the two orders is not enough: when
 * categories share an order (every category used to be created with 0), a swap
 * changes nothing. The list is renumbered 0..n-1 in its new order instead, and
 * only the categories whose order actually changes are returned.
 */
export function displayOrderUpdatesForMove(
  sorted: Pick<Category, 'id' | 'display_order'>[],
  categoryId: string,
  direction: 'up' | 'down'
): { id: string; display_order: number }[] {
  const from = sorted.findIndex((c) => c.id === categoryId)
  const to = direction === 'up' ? from - 1 : from + 1
  if (from < 0 || to < 0 || to >= sorted.length) return []

  const reordered = [...sorted]
  ;[reordered[from], reordered[to]] = [reordered[to], reordered[from]]
  return reordered
    .map((c, index) => ({ id: c.id, display_order: index, current: c.display_order }))
    .filter((c) => c.display_order !== c.current)
    .map(({ id, display_order }) => ({ id, display_order }))
}

// ==================== Product-Category Assignment ====================

/**
 * Assign a product to a category
 */
export async function assignProductToCategory(categoryId: string, productId: string): Promise<void> {
  return apiClient.post(`/api/v1/categories/${categoryId}/products/${productId}`, {})
}

/**
 * Remove a product from a category
 */
export async function removeProductFromCategory(categoryId: string, productId: string): Promise<void> {
  return apiClient.delete(`/api/v1/categories/${categoryId}/products/${productId}`)
}
