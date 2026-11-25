/**
 * The standard packaging catalogue and the one-time seeding notice (spec 006,
 * contracts/packaging-catalogue-api.md).
 *
 * Sizes and the typical cost are decimal strings, as every figure is
 * (Constitution IV): rendered, never parsed for arithmetic.
 */

import type { PackagingKind } from './packaging'

export interface CatalogueItem {
  key: string
  name: string
  kind: PackagingKind
  inner_length_mm: string | null
  inner_width_mm: string | null
  inner_height_mm: string | null
  wall_mm: string | null
  empty_weight_grams: string | null
  fill_volume_ml: string | null
  unit_of_measure: string
  /** In the shop's books currency; null when the catalogue has no price in it. */
  typical_cost: string | null
  source: string
  /** The shop already has a row seeded from this entry. */
  present: boolean
  present_as: string | null
  /** Seeded once and since deleted: offered, but the operator may leave it out. */
  previously_removed: boolean
}

export interface PackagingCatalogue {
  version: number
  as_of: string
  currency: string
  items: CatalogueItem[]
}

export type CatalogueSkipReason = 'already_present' | 'name_in_use'

export interface CatalogueApplyResult {
  added: { key: string; id: string }[]
  skipped: { key: string; reason: CatalogueSkipReason }[]
}

export type CarrierChoiceReason =
  | 'no_carrier_for_country'
  | 'no_carrier_for_currency'
  | 'carrier_currency_mismatch'

export interface PackagingNotice {
  version: number | null
  applied_at: string
  added: string[]
  skipped: { key: string; reason: CatalogueSkipReason }[]
}

export interface PostageNotice {
  carrier: string | null
  chosen_from: 'country' | 'currency' | 'operator' | null
  tariff_version: string | null
  applied_at: string
  added: number
  superseded: number
  skipped: { service: string; zone: string; min_grams: string; reason: string }[]
  reason: CarrierChoiceReason | null
}

/** The parts the operator has not dismissed yet; `{}` when none. */
export interface CatalogueNotice {
  packaging?: PackagingNotice
  postage?: PostageNotice
}

export type NoticePart = 'packaging' | 'postage'
