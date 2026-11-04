/**
 * TypeScript types for Spool API
 * These match the Pydantic schemas in backend/app/schemas/spool.py
 */

import type { Money } from '@/types/pricing'

// Base spool fields (used for creation and responses)
export interface SpoolBase {
  spool_id: string
  material_type_id: string // UUID
  brand: string
  color: string
  color_hex?: string | null // Hex color code (e.g., FF5733)
  finish?: string | null

  // Filament specifications
  diameter: number // Typically 1.75 or 2.85mm
  density?: number | null // g/cm³
  extruder_temp?: number | null // Recommended extruder temp °C
  bed_temp?: number | null // Recommended bed temp °C

  // Special filament properties
  translucent: boolean
  glow: boolean
  pattern?: string | null // marble, gradient, speckled, etc.
  spool_type?: string | null // cardboard, plastic, refill, etc.

  // Weight tracking
  initial_weight: number
  current_weight: number
  empty_spool_weight?: number | null

  // Purchase info
  purchase_date?: string | null // ISO 8601 date string
  // A decimal **string**, not a number. The column is `Numeric` and
  // `SpoolBase.purchase_price` is a `Decimal`, which Pydantic serialises as a
  // string -- and the figure feeds `landed_cost.py` and the per-gram material
  // price, so a double here is the one lossy step in that chain
  // (Constitution IV, task T158).
  purchase_price?: Money | null
  supplier?: string | null

  // Batch tracking
  purchased_quantity: number
  spools_remaining: number

  // Organization
  storage_location?: string | null
  notes?: string | null
  qr_code_id?: string | null
  is_active: boolean
}

// Create spool request (POST /api/v1/spools)
export type SpoolCreate = SpoolBase

// Update spool request (PUT /api/v1/spools/{id}).
// Mirrors `SpoolUpdate` in backend/app/schemas/spool.py: spool-level fields
// only. Brand, colour and material belong to the filament type; the API
// ignores them here, so they are not part of this type (bug
// spool-create-missing-filament-type).
export interface SpoolUpdate {
  spool_id?: string
  filament_type_id?: string

  initial_weight?: number
  current_weight?: number
  empty_spool_weight?: number | null

  purchase_date?: string | null
  purchase_price?: Money | null
  supplier?: string | null

  storage_location?: string | null
  qr_code_id?: string | null
  is_active?: boolean
  is_labeled?: boolean
}

/**
 * The filament type a spool belongs to, as `SpoolResponse.filament_type`
 * carries it (`FilamentTypeResponse` in `backend/app/schemas/filament_type.py`).
 *
 * Brand, colour, material and the print specifications live here, not on the
 * spool: the API stopped sending them flat when a spool became one physical
 * reel of a filament type. Read them through `@/lib/spool`, which tolerates a
 * spool whose type is missing.
 */
export interface SpoolFilamentType {
  id: string // UUID
  material_type_id: string // UUID
  brand: string
  color: string
  color_hex?: string | null
  finish?: string | null
  pattern?: string | null
  spool_type?: string | null
  diameter: number
  density?: number | null
  extruder_temp?: number | null
  bed_temp?: number | null
  translucent: boolean
  glow: boolean
  notes?: string | null
  material_type_code: string
  material_type_name: string
}

// Spool response (GET /api/v1/spools/{id} or in list).
// Mirrors `SpoolResponse` in backend/app/schemas/spool.py: spool-level fields
// only, with the filament type nested. It deliberately does not extend
// `SpoolBase`, whose flat brand/colour/material the API no longer returns.
export interface SpoolResponse {
  id: string // UUID
  tenant_id: string // UUID
  spool_id: string
  filament_type_id: string // UUID

  // Weight tracking
  initial_weight: number
  current_weight: number
  empty_spool_weight?: number | null

  // Purchase info
  purchase_date?: string | null
  purchase_price?: Money | null
  supplier?: string | null

  // Organization
  storage_location?: string | null
  qr_code_id?: string | null
  is_active: boolean
  is_labeled?: boolean

  created_at: string // ISO 8601 datetime string
  updated_at: string // ISO 8601 datetime string

  // Computed fields
  remaining_weight: number
  remaining_percentage: number
  /** Landed cost per usable gram, derived by the server; null when underivable. */
  cost_per_gram?: string | null

  filament_type?: SpoolFilamentType | null
}

// List response (GET /api/v1/spools)
export interface SpoolListResponse {
  total: number
  spools: SpoolResponse[]
  page: number
  page_size: number
}

// Query parameters for list endpoint
export interface SpoolListParams {
  page?: number
  page_size?: number
  search?: string
  material_type_id?: string
  is_active?: boolean
  low_stock_only?: boolean
}

// Material Type (from backend reference data)
export interface MaterialType {
  id: string // UUID
  name: string
  code: string
  description?: string | null
  typical_density?: number | null
  /**
   * A decimal string, not a number. T154 converted this to `Decimal` at
   * `app/schemas/material.py`, so it crosses the wire as a string -- the same
   * mismatch T158 found on `purchase_price`, left on the sibling field. It
   * prefills a spool's purchase price rather than entering the engine
   * directly, so the exposure is narrow and the type was still wrong (FR-047).
   */
  typical_cost_per_kg?: Money | null
  min_temp?: number | null
  max_temp?: number | null
  bed_temp?: number | null
  created_at: string
  updated_at: string
}
