/**
 * Carrier postage: the carriers Batchivo ships tariffs for, the shop's
 * carrier and default service, and newer tariffs on offer (spec 006,
 * contracts/postage-catalogue-api.md).
 */

import type { CarrierChoiceReason } from './packagingCatalogue'

export interface CarrierService {
  key: string
  name: string
  /** This shop has seeded rows of it in force. */
  seeded: boolean
  has_size_limits: boolean
}

export interface Carrier {
  key: string
  name: string
  currency: string
  /** Priced in the shop's books currency. */
  usable: boolean
  latest_tariff: string | null
  source: string | null
  services: CarrierService[]
}

export interface CurrentPostage {
  carrier: string | null
  /** '<carrier>:<service>', or null for the cheapest fitting service. */
  default_service: string | null
  tariff_version: string | null
}

export interface CarriersResponse {
  suggested_carrier: string | null
  /** What the country or currency names, even when it cannot be used. */
  candidate_carrier: string | null
  chosen_from: 'country' | 'currency'
  reason: CarrierChoiceReason | null
  current: CurrentPostage
  carriers: Carrier[]
}

export interface CarrierApply {
  carrier: string
  /** Absent or empty: every service. */
  services?: string[]
  /** Null: the latest shipped tariff. */
  tariff_version?: string | null
}

export interface CarrierApplyResult {
  added: number
  superseded: number
  skipped: { service: string; zone: string; min_grams: string; reason: string }[]
}

export interface TariffUpdate {
  carrier: string
  current: string
  latest: string
  effective_from: string
  source: string
}

export interface PostageSettings {
  carrier: string | null
  default_service: string | null
}

/** The key a product or the shop names a service by. */
export function serviceKey(carrier: string, service: string): string {
  return `${carrier}:${service}`
}
