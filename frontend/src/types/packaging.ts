/**
 * Packaging advisor types (feature 003, contracts/packaging-api.md).
 *
 * Every length, weight and volume is a decimal **string** ("120.0"), as money
 * is: a figure that arrived as a JavaScript number has already been through a
 * float (Constitution IV). Nothing here is ever parsed for arithmetic.
 */

export type DimensionSource = 'entered' | 'measured'

/** An item's dimensions with where they came from (FR-001, FR-002). */
export interface Dimensions {
  length_mm: string | null
  width_mm: string | null
  height_mm: string | null
  source: DimensionSource | null
  source_file_id: string | null
  set_at: string | null
  /** A variant showing its product's dimensions. */
  inherited: boolean
}

/** Dimensions to save; all three null clears them. */
export interface DimensionsInput {
  length_mm: string | null
  width_mm: string | null
  height_mm: string | null
  /** Adopt that model file's measurement instead (source "measured"). */
  adopt_file_id?: string | null
}

export interface InnerSize {
  length_mm: string
  width_mm: string
  height_mm: string
}

export interface ItemSize extends InnerSize {
  source: DimensionSource | null
}

export interface PackagingSuggestion {
  consumable_id: string
  name: string
  kind: 'box' | 'mailer'
  in_stock: boolean
  inner: InnerSize
  /** For each of the box's axes, which of the item's lies along it. */
  orientation: ['length' | 'width' | 'height', 'length' | 'width' | 'height', 'length' | 'width' | 'height']
  /** Room left on each axis beyond the clearance. */
  room_mm: { length: string; width: string; height: string }
  empty_volume_ml: string
  void_fill: { consumable_id: string; name: string; quantity: number } | null
  wrap: { consumable_id: string; name: string } | null
  is_current: boolean
}

/** Suggestions carry no cost: the packaging cost is the cost breakdown's (FR-021). */
export interface PackagingSuggestions {
  item: ItemSize | null
  clearance_mm: string
  fragile: boolean
  suggestions: PackagingSuggestion[]
  minimum_inner: InnerSize | null
  warnings: string[]
}

export interface AcceptPackagingInput {
  consumable_id: string
  quantity: number
  variant_id?: string | null
}

export interface EffectivePackaging {
  consumable_id: string
  name: string
  quantity: number
  inherited: boolean
}

/** The clearance kept around an item on every side, in mm (FR-015). */
export interface PackagingSettings {
  clearance_mm: string
  fragile_clearance_mm: string
  /** False while the figures are the defaults (research D8). */
  configured: boolean
}

export type PackagingSettingsInput = Omit<PackagingSettings, 'configured'>

/** A model file's measured bounding box (research D3/D4). */
export interface FileMeasurement {
  length_mm: string | null
  width_mm: string | null
  height_mm: string | null
  objects: { name: string; length_mm: string; width_mm: string; height_mm: string }[]
  note: string | null
  status: 'done' | 'pending' | 'skipped' | 'failed'
  /** Which records took it automatically; empty when only offered. */
  applied_to: ('model' | 'product')[]
}

export type PackagingKind = 'box' | 'mailer' | 'void_fill' | 'wrap'

// ---------------------------------------------------------------------------
// Orders (Phase 2)
// ---------------------------------------------------------------------------

export interface OrderParcelSuggestion {
  consumable_id: string
  name: string
  contents: { product_id: string; sku: string; quantity: number }[]
  outer_mm: InnerSize | null
  packed_weight_grams: string | null
  void_fill: { consumable_id: string; name: string; quantity: number } | null
  /** What assembling the parcel assumed, e.g. a wall taken as 0 mm. */
  notes?: string[]
}

export interface EstimatedPostage {
  amount: string | null
  zone: string | null
  reason: string | null
  is_estimate: boolean
  notes?: string[]
}

export interface OrderPackagingSuggestions {
  parcels: OrderParcelSuggestion[]
  estimated_postage: EstimatedPostage
  warnings: { code: string; sku?: string | null }[]
}

export interface ParcelItemInput {
  consumable_id: string
  quantity: number
}

export interface ConfirmParcelsInput {
  parcels: {
    items: ParcelItemInput[]
    /** Which units are in this parcel; needed when there are several. */
    contents?: { sku: string; quantity: number }[] | null
  }[]
}

export interface ConfirmedParcelItem {
  consumable_id: string
  name: string | null
  quantity: number
}

export interface ConfirmedParcel {
  id: string
  sequence: number
  outer_length_mm: string | null
  outer_width_mm: string | null
  outer_height_mm: string | null
  packed_weight_grams: string | null
  confirmed_at: string
  items: ConfirmedParcelItem[]
}

export interface StockWarning {
  code: 'stock_below_zero'
  consumable_id: string
  on_hand: number
}

export interface ConfirmParcelsResult {
  parcels: ConfirmedParcel[]
  postage: EstimatedPostage
  warnings: StockWarning[]
}
