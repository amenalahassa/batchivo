/**
 * Display helpers for a spool's filament type.
 *
 * A spool's brand, colour and material belong to its filament type, which the
 * API nests under `spool.filament_type`. Screens that read them flat showed
 * "FIL-002 - undefined (undefined)" and crashed when sorting (bug
 * spool-flat-fields-undefined). Every screen reads them through these helpers,
 * which also cope with a spool whose filament type is missing.
 */

import type { SpoolResponse } from '@/types/spool'

type SpoolLike = Pick<SpoolResponse, 'spool_id' | 'filament_type'>

export function spoolBrand(spool: SpoolLike): string {
  return spool.filament_type?.brand ?? ''
}

export function spoolColor(spool: SpoolLike): string {
  return spool.filament_type?.color ?? ''
}

export function spoolColorHex(spool: SpoolLike): string | null {
  return spool.filament_type?.color_hex ?? null
}

export function spoolMaterialCode(spool: SpoolLike): string {
  return spool.filament_type?.material_type_code ?? ''
}

export function spoolMaterialName(spool: SpoolLike): string {
  return spool.filament_type?.material_type_name ?? ''
}

/** "Brand Colour", or the spool's own id when it has no filament type. */
export function spoolName(spool: SpoolLike): string {
  const name = `${spoolBrand(spool)} ${spoolColor(spool)}`.trim()
  return name || spool.spool_id
}

/** "FIL-002 - PLA Basic (Jade White)", leaving out whatever is unknown. */
export function spoolLabel(spool: SpoolLike): string {
  const material = spoolMaterialName(spool)
  const color = spoolColor(spool)
  let label = spool.spool_id
  if (material) label += ` - ${material}`
  if (color) label += ` (${color})`
  return label
}

export type SpoolSortOption = 'spool_id' | 'material' | 'brand' | 'color' | 'remaining' | 'weight'

/**
 * The spool list's client-side order. Material, brand and colour are read
 * through the helpers above: comparing the flat fields threw
 * `Cannot read properties of undefined (reading 'localeCompare')`.
 */
export function sortSpools<T extends SpoolResponse>(spools: T[], sortBy: SpoolSortOption): T[] {
  return [...spools].sort((a, b) => {
    switch (sortBy) {
      case 'spool_id':
        // Natural order: FIL-001 before FIL-009 before FIL-010.
        return a.spool_id.localeCompare(b.spool_id, undefined, {
          numeric: true,
          sensitivity: 'base',
        })
      case 'material':
        return spoolMaterialCode(a).localeCompare(spoolMaterialCode(b))
      case 'brand':
        return spoolBrand(a).localeCompare(spoolBrand(b))
      case 'color':
        return spoolColor(a).localeCompare(spoolColor(b))
      case 'remaining':
        return b.remaining_percentage - a.remaining_percentage // Descending
      case 'weight':
        return b.current_weight - a.current_weight // Descending
      default:
        return 0
    }
  })
}
