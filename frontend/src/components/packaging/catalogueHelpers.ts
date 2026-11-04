/**
 * Labels and small helpers the packaging screens share (spec 006). Kept out
 * of the component files so fast refresh stays component-only.
 */

import type { PackagingKind } from '@/types/packaging'
import type { CarrierChoiceReason, CatalogueItem } from '@/types/packagingCatalogue'

export const PACKAGING_KIND_LABELS: Record<PackagingKind, string> = {
  box: 'Box',
  mailer: 'Mailer',
  void_fill: 'Void fill',
  wrap: 'Wrap',
}

export const PACKAGING_KINDS: PackagingKind[] = ['box', 'mailer', 'void_fill', 'wrap']

/** The Packaging page's list query: packaging kinds only. */
export const packagingListParams = {
  packaging_kind: PACKAGING_KINDS.join(','),
  page: 1,
  page_size: 100,
}

export const CHOICE_REASONS: Record<CarrierChoiceReason, string> = {
  no_carrier_for_country: 'Batchivo has no carrier tariff for your shop’s country yet.',
  no_carrier_for_currency: 'Batchivo has no carrier tariff priced in your books currency yet.',
  carrier_currency_mismatch:
    'The carrier for your country prices in a different currency from your books, so its tariff was not added.',
}

export function itemSize(item: CatalogueItem): string {
  if (item.kind === 'void_fill') return item.fill_volume_ml ? `${item.fill_volume_ml} ml` : '—'
  if (item.inner_length_mm && item.inner_width_mm && item.inner_height_mm) {
    return `${item.inner_length_mm} × ${item.inner_width_mm} × ${item.inner_height_mm} mm`
  }
  return '—'
}

/** Every item not already present, which is what "add all" adds. */
export function selectableKeys(items: CatalogueItem[]): string[] {
  return items.filter((i) => !i.present).map((i) => i.key)
}
