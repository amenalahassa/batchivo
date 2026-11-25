/**
 * Packaging advisor API client (feature 003).
 *
 * Dimensions, box suggestions, accepting a box, the clearance settings, and
 * at dispatch the order's parcel suggestion and confirmation.
 */

import { apiClient } from '../api'
import type {
  AcceptPackagingInput,
  ConfirmParcelsInput,
  ConfirmParcelsResult,
  Dimensions,
  DimensionsInput,
  OrderPackagingSuggestions,
  PackagingSettings,
  PackagingSettingsInput,
  PackagingSuggestions,
} from '@/types/packaging'

export async function setProductDimensions(
  productId: string,
  data: DimensionsInput,
): Promise<Dimensions> {
  return apiClient.put<Dimensions>(`/api/v1/products/${productId}/dimensions`, data)
}

export async function setModelDimensions(
  modelId: string,
  data: DimensionsInput,
): Promise<Dimensions> {
  return apiClient.put<Dimensions>(`/api/v1/models/${modelId}/dimensions`, data)
}

export async function setVariantDimensions(
  productId: string,
  variantId: string,
  data: DimensionsInput,
): Promise<Dimensions> {
  return apiClient.put<Dimensions>(
    `/api/v1/products/${productId}/variants/${variantId}/dimensions`,
    data,
  )
}

export async function getPackagingSuggestions(
  productId: string,
  variantId?: string | null,
): Promise<PackagingSuggestions> {
  return apiClient.get<PackagingSuggestions>(
    `/api/v1/products/${productId}/packaging-suggestions`,
    { params: variantId ? { variant_id: variantId } : undefined },
  )
}

export async function acceptPackaging(
  productId: string,
  data: AcceptPackagingInput,
): Promise<void> {
  await apiClient.post(`/api/v1/products/${productId}/packaging`, data)
}

export async function getPackagingSettings(): Promise<PackagingSettings> {
  return apiClient.get<PackagingSettings>('/api/v1/settings/packaging')
}

export async function updatePackagingSettings(
  data: PackagingSettingsInput,
): Promise<PackagingSettings> {
  return apiClient.put<PackagingSettings>('/api/v1/settings/packaging', data)
}

export async function getOrderPackagingSuggestions(
  orderId: string,
): Promise<OrderPackagingSuggestions> {
  return apiClient.get<OrderPackagingSuggestions>(
    `/api/v1/orders/${orderId}/packaging-suggestions`,
  )
}

export async function confirmOrderParcels(
  orderId: string,
  data: ConfirmParcelsInput,
): Promise<ConfirmParcelsResult> {
  return apiClient.post<ConfirmParcelsResult>(
    `/api/v1/orders/${orderId}/parcels`,
    data,
  )
}
