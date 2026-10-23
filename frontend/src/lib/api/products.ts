/**
 * Product API client
 *
 * Provides TypeScript functions for interacting with the products API endpoints.
 * Products are sellable items composed of one or more Models with per-channel pricing.
 */

import { apiClient } from '../api'

// ==================== Types ====================

/**
 * Product cost breakdown
 */
export interface ProductCostBreakdown {
  models_cost: string
  child_products_cost: string
  packaging_cost: string
  assembly_cost: string
  total_make_cost: string
  // Phase 3: Actual cost tracking from production runs
  models_actual_cost?: string
  total_actual_cost?: string
  cost_variance_percentage?: string
  models_with_actual_cost: number
  models_total: number
}

/**
 * Product-Model relationship with model details
 */
export interface ProductModel {
  id: string
  product_id: string
  model_id: string
  quantity: number
  model_name?: string
  model_sku?: string
  model_cost?: string
  created_at: string
}

/**
 * Product-Component relationship (product containing another product)
 */
export interface ProductComponent {
  id: string
  parent_product_id: string
  child_product_id: string
  quantity: number
  child_product_name?: string
  child_product_sku?: string
  child_product_cost?: string
  created_at: string
}

/**
 * Product pricing for a sales channel with profit calculations
 */
export interface ProductPricing {
  id: string
  product_id: string
  sales_channel_id: string
  list_price: string
  is_active: boolean
  /**
   * First day this price applied (FR-039). A price without its period reads
   * as though it had always been the price, which is what made a historical
   * margin unanswerable before Tier 3.
   */
  valid_from: string
  /** Last day it applied, or null for the price in effect now. */
  valid_to: string | null
  /** True for the row in effect now, i.e. the one with no `valid_to`. */
  is_current: boolean
  /**
   * Lower bound of the quantity tier this price applies from. Tiers are
   * half-open, so at exactly a break quantity the highest tier reached wins.
   */
  min_quantity: number
  channel_name?: string
  platform_type?: string
  platform_fee?: string
  net_revenue?: string
  profit?: string
  margin_percentage?: string
  created_at: string
  updated_at: string
}

/**
 * Basic product info (for list views)
 */
export interface Product {
  id: string
  tenant_id: string
  sku: string
  name: string
  description?: string
  packaging_cost: string
  packaging_consumable_id?: string | null
  packaging_quantity: number
  assembly_minutes: number
  units_in_stock: number
  is_active: boolean
  created_at: string
  updated_at: string
  // Computed fields for list views
  total_make_cost?: string
  /**
   * What the engine could not cost. Non-empty means `total_make_cost` is a
   * floor rather than a cost, and the row must say so (FR-019).
   */
  incomplete_reasons?: string[]
  // No suggested_price. The backend used to serve total_make_cost * 2.5 and
  // this rendered it as "SRP"; a price comes from the pricing engine now --
  // the solver and ladder on the pricing editor (FR-007/FR-048).
  // Shop display fields
  shop_visible: boolean
  shop_description?: string
  is_featured: boolean
  is_dragon: boolean
  feature_title?: string
  backstory?: string
  print_to_order: boolean
  // Designer
  designer_id?: string
  designer_name?: string
  designer_slug?: string
  // Product specifications
  weight_grams?: number
  size_cm?: string
  print_time_hours?: string
}

/**
 * Brief category info for product
 */
export interface ProductCategoryBrief {
  id: string
  name: string
  slug: string
}

/**
 * External listing info (Etsy, eBay, etc.)
 */
export interface ExternalListing {
  id: string
  platform: string
  external_id: string
  external_url?: string
  sync_status: 'synced' | 'pending' | 'error'
  last_synced_at?: string
}

/**
 * Full product detail with models, child products, pricing, and cost breakdown
 */
export interface ProductDetail extends Product {
  models: ProductModel[]
  child_products: ProductComponent[]
  pricing: ProductPricing[]
  cost_breakdown: ProductCostBreakdown
  // Packaging consumable info (if linked)
  packaging_consumable_name?: string
  packaging_consumable_sku?: string
  packaging_consumable_cost?: string
  // Categories
  categories: ProductCategoryBrief[]
  // External marketplace listings
  external_listings: ExternalListing[]
}

export interface ProductListResponse {
  products: Product[]
  total: number
  skip: number
  limit: number
}

/**
 * Request to create a product-model relationship
 */
export interface ProductModelCreateRequest {
  model_id: string
  quantity: number
}

/**
 * Request to create a product-component relationship (adding a child product)
 */
export interface ProductComponentCreateRequest {
  child_product_id: string
  quantity: number
}

/**
 * Request to update a product-component relationship
 */
export interface ProductComponentUpdateRequest {
  quantity: number
}

/**
 * Request to create a new product
 */
export interface ProductCreateRequest {
  sku: string
  name: string
  description?: string
  packaging_cost?: string
  packaging_consumable_id?: string | null
  packaging_quantity?: number
  assembly_minutes?: number
  units_in_stock?: number
  is_active?: boolean
  models?: ProductModelCreateRequest[]
  child_products?: ProductComponentCreateRequest[]
  // Product specifications
  weight_grams?: number | null
  size_cm?: string | null
  print_time_hours?: string | null
}

/**
 * Request to update a product
 */
export interface ProductUpdateRequest {
  sku?: string
  name?: string
  description?: string
  packaging_cost?: string
  packaging_consumable_id?: string | null
  packaging_quantity?: number
  assembly_minutes?: number
  units_in_stock?: number
  is_active?: boolean
  // Shop display fields
  shop_visible?: boolean
  shop_description?: string | null
  is_featured?: boolean
  is_dragon?: boolean
  feature_title?: string | null
  backstory?: string | null
  print_to_order?: boolean
  // Designer
  designer_id?: string | null
  // Product specifications
  weight_grams?: number | null
  size_cm?: string | null
  print_time_hours?: string | null
}

/**
 * Request to create pricing for a sales channel
 */
export interface ProductPricingCreateRequest {
  sales_channel_id: string
  list_price: string
  is_active?: boolean
  /** Lower bound of the quantity tier. Omitted means the base tier, 1. */
  min_quantity?: number
  /** Backdates the period. Omitted means today. */
  valid_from?: string
}

/**
 * Request to update pricing
 *
 * A price change **closes the current period and opens a new one** rather
 * than editing the row, so a settled order still reports the price it was
 * charged (FR-039). `is_active` is the exception: delisting is a status, not
 * a price, so it edits the current row in place.
 */
export interface ProductPricingUpdateRequest {
  list_price?: string
  is_active?: boolean
  /** First day the new price applies. Omitted means today. */
  valid_from?: string
}

export interface ProductListParams {
  skip?: number
  limit?: number
  search?: string
  is_active?: boolean
}

// ==================== API Functions ====================

/**
 * List all products with pagination and filtering
 */
export async function listProducts(params?: ProductListParams): Promise<ProductListResponse> {
  const queryParams = new URLSearchParams()

  if (params?.skip !== undefined) queryParams.append('skip', params.skip.toString())
  if (params?.limit !== undefined) queryParams.append('limit', params.limit.toString())
  if (params?.search) queryParams.append('search', params.search)
  if (params?.is_active !== undefined) queryParams.append('is_active', params.is_active.toString())

  const url = `/api/v1/products${queryParams.toString() ? `?${queryParams.toString()}` : ''}`
  return apiClient.get<ProductListResponse>(url)
}

/**
 * Get a single product by ID with full details (models, pricing, cost breakdown)
 */
export async function getProduct(productId: string): Promise<ProductDetail> {
  return apiClient.get<ProductDetail>(`/api/v1/products/${productId}`)
}

/**
 * Create a new product
 * Can optionally include models to add during creation
 */
export async function createProduct(data: ProductCreateRequest): Promise<ProductDetail> {
  return apiClient.post<ProductDetail>('/api/v1/products', data)
}

/**
 * Update an existing product
 */
export async function updateProduct(productId: string, data: ProductUpdateRequest): Promise<ProductDetail> {
  return apiClient.put<ProductDetail>(`/api/v1/products/${productId}`, data)
}

/**
 * Delete a product (soft delete - sets is_active=false)
 */
export async function deleteProduct(productId: string): Promise<void> {
  return apiClient.delete(`/api/v1/products/${productId}`)
}

// ==================== Product Models (Composition) Operations ====================

/**
 * Add a model to product composition
 */
export async function addProductModel(
  productId: string,
  data: ProductModelCreateRequest
): Promise<ProductModel> {
  return apiClient.post<ProductModel>(`/api/v1/products/${productId}/models`, data)
}

/**
 * Update a model's quantity in product composition
 */
export async function updateProductModel(
  productId: string,
  productModelId: string,
  data: ProductModelCreateRequest
): Promise<ProductModel> {
  return apiClient.put<ProductModel>(`/api/v1/products/${productId}/models/${productModelId}`, data)
}

/**
 * Remove a model from product composition
 */
export async function removeProductModel(productId: string, productModelId: string): Promise<void> {
  return apiClient.delete(`/api/v1/products/${productId}/models/${productModelId}`)
}

// ==================== Product Pricing Operations ====================

/**
 * Add pricing for a product on a sales channel
 */
export async function addProductPricing(
  productId: string,
  data: ProductPricingCreateRequest
): Promise<ProductPricing> {
  return apiClient.post<ProductPricing>(`/api/v1/products/${productId}/pricing`, data)
}

/**
 * Update product pricing
 */
export async function updateProductPricing(
  productId: string,
  pricingId: string,
  data: ProductPricingUpdateRequest
): Promise<ProductPricing> {
  return apiClient.put<ProductPricing>(`/api/v1/products/${productId}/pricing/${pricingId}`, data)
}

/**
 * Every price this product has carried on a channel, newest period first
 *
 * Deliberately carries **no** profit or margin figures. Valuing a past price
 * against today's cost is the restatement FR-038 exists to prevent; a settled
 * order's own snapshot is where a historical margin lives.
 */
export async function getProductPricingHistory(
  productId: string,
  salesChannelId: string
): Promise<ProductPricing[]> {
  return apiClient.get<ProductPricing[]>(
    `/api/v1/products/${productId}/pricing/${salesChannelId}/history`
  )
}

/**
 * Remove product pricing for a sales channel
 *
 * Closes the current period rather than deleting it, so the prices past
 * orders were charged stay readable.
 */
export async function removeProductPricing(productId: string, pricingId: string): Promise<void> {
  return apiClient.delete(`/api/v1/products/${productId}/pricing/${pricingId}`)
}

// ==================== Product Components (Bundle Composition) Operations ====================

/**
 * Add a child product to a parent product (create a bundle)
 */
export async function addProductComponent(
  productId: string,
  data: ProductComponentCreateRequest
): Promise<ProductComponent> {
  return apiClient.post<ProductComponent>(`/api/v1/products/${productId}/components`, data)
}

/**
 * Update a child product's quantity in the bundle
 */
export async function updateProductComponent(
  productId: string,
  componentId: string,
  data: ProductComponentUpdateRequest
): Promise<ProductComponent> {
  return apiClient.put<ProductComponent>(`/api/v1/products/${productId}/components/${componentId}`, data)
}

/**
 * Remove a child product from the bundle
 */
export async function removeProductComponent(productId: string, componentId: string): Promise<void> {
  return apiClient.delete(`/api/v1/products/${productId}/components/${componentId}`)
}

// ==================== Helpers ====================
//
// Three helpers used to live here and all three are gone, with no caller
// anywhere in `src/` at the time of removal:
//
// - `calculateTotalModelsCost` and `calculateTotalChildProductsCost` summed a
//   bill-of-materials cost in the browser as `parseFloat(cost) * quantity`.
//   That recursive cost has one authority, `app/services/costing.py`, which
//   walks bundles with its own cycle detection and depth guard. Constitution
//   III calls a second implementation of a domain calculation a defect whether
//   or not its output currently agrees -- and an exported one with no reader is
//   one import away from having one.
// - `formatCurrency` was a third money renderer doing `parseFloat(value)
//   .toFixed(2)` behind a hardcoded `£`. `formatMoney` in `@/lib/money` is the
//   one renderer, and `useCurrency()` delegates to it for the tenant's symbol.
//
// Read a cost from the API; render it with `formatMoney` (FR-048).

// ==================== Product Images ====================

/**
 * Product image info
 */
export interface ProductImage {
  id: string
  product_id: string
  image_url: string
  thumbnail_url?: string
  alt_text: string
  display_order: number
  is_primary: boolean
  original_filename?: string
  file_size?: number
  content_type?: string
  created_at: string
  updated_at: string
}

/**
 * Upload an image for a product
 * Uses extended timeout (60s) for large files
 */
export async function uploadProductImage(
  productId: string,
  file: File,
  altText: string = ''
): Promise<ProductImage> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await apiClient.post<ProductImage>(
    `/api/v1/products/${productId}/images?alt_text=${encodeURIComponent(altText)}`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 60000, // 60 seconds for large file uploads
    }
  )
  return response
}

/**
 * Get images for a product
 */
export async function getProductImages(productId: string): Promise<ProductImage[]> {
  const response = await apiClient.get<{ images: ProductImage[]; total: number }>(
    `/api/v1/products/${productId}/images`
  )
  return response.images
}

/**
 * Update image alt text or display order
 */
export async function updateProductImage(
  productId: string,
  imageId: string,
  data: { alt_text?: string; display_order?: number }
): Promise<ProductImage> {
  const response = await apiClient.patch<ProductImage>(
    `/api/v1/products/${productId}/images/${imageId}`,
    data
  )
  return response
}

/**
 * Set an image as the primary image
 */
export async function setPrimaryImage(productId: string, imageId: string): Promise<ProductImage> {
  const response = await apiClient.post<ProductImage>(
    `/api/v1/products/${productId}/images/${imageId}/set-primary`
  )
  return response
}

/**
 * Delete a product image
 */
export async function deleteProductImage(productId: string, imageId: string): Promise<void> {
  await apiClient.delete(`/api/v1/products/${productId}/images/${imageId}`)
}

/**
 * Rotate a product image clockwise
 */
export async function rotateProductImage(
  productId: string,
  imageId: string,
  degrees: number = 90
): Promise<ProductImage> {
  const response = await apiClient.post<ProductImage>(
    `/api/v1/products/${productId}/images/${imageId}/rotate?degrees=${degrees}`
  )
  return response
}

// ==================== Etsy Sync ====================

/**
 * Sync response from Etsy sync operation
 */
export interface SyncToEtsyResponse {
  success: boolean
  message: string
  listing?: ExternalListing
  etsy_url?: string
}

/**
 * Sync a product to Etsy
 * Creates a new listing or updates existing one
 */
export async function syncProductToEtsy(
  productId: string,
  force: boolean = false
): Promise<SyncToEtsyResponse> {
  return apiClient.post<SyncToEtsyResponse>(
    `/api/v1/products/${productId}/sync/etsy`,
    { force }
  )
}
