/**
 * @vitest-environment node
 *
 * Spool display helpers (bug spool-flat-fields-undefined).
 *
 * The spool API nests brand, colour and material under `filament_type`.
 * Screens that read them flat rendered "FIL-002 - undefined (undefined)" and
 * the spool list threw when sorted by material, brand or colour.
 */

import { describe, expect, it } from 'vitest'

import type { SpoolResponse } from '@/types/spool'

import {
  sortSpools,
  spoolBrand,
  spoolColor,
  spoolLabel,
  spoolMaterialCode,
  spoolName,
} from './spool'

function spool(
  spoolId: string,
  filamentType: { brand: string; color: string; code: string; name: string } | null,
  overrides: Partial<SpoolResponse> = {},
): SpoolResponse {
  return {
    id: `id-${spoolId}`,
    tenant_id: 'tenant',
    spool_id: spoolId,
    filament_type_id: 'ft',
    initial_weight: 1000,
    current_weight: 500,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    remaining_weight: 500,
    remaining_percentage: 50,
    filament_type: filamentType && {
      id: 'ft',
      material_type_id: 'mat',
      brand: filamentType.brand,
      color: filamentType.color,
      diameter: 1.75,
      translucent: false,
      glow: false,
      material_type_code: filamentType.code,
      material_type_name: filamentType.name,
    },
    ...overrides,
  }
}

const jade = spool('FIL-002', { brand: 'Bambu Lab', color: 'Jade White', code: 'PLA', name: 'PLA Basic' })
const orphan = spool('FIL-009', null)

describe('spool display helpers', () => {
  it('labels a BOM line from the nested filament type', () => {
    expect(spoolLabel(jade)).toBe('FIL-002 - PLA Basic (Jade White)')
  })

  it('never prints undefined for a spool without a filament type', () => {
    expect(spoolLabel(orphan)).toBe('FIL-009')
    expect(spoolName(orphan)).toBe('FIL-009')
    expect(spoolBrand(orphan)).toBe('')
    expect(spoolColor(orphan)).toBe('')
    expect(spoolMaterialCode(orphan)).toBe('')
  })

  it('names a spool by brand and colour', () => {
    expect(spoolName(jade)).toBe('Bambu Lab Jade White')
  })
})

describe('sortSpools', () => {
  const petg = spool('FIL-010', { brand: 'eSun', color: 'Red', code: 'PETG', name: 'PETG' })
  const list = [petg, jade, orphan]

  it.each(['material', 'brand', 'color'] as const)('sorts by %s without throwing', (sortBy) => {
    expect(() => sortSpools(list, sortBy)).not.toThrow()
  })

  it('orders by material code', () => {
    expect(sortSpools(list, 'material').map((s) => s.spool_id)).toEqual([
      'FIL-009',
      'FIL-010',
      'FIL-002',
    ])
  })

  it('orders spool ids naturally', () => {
    expect(sortSpools(list, 'spool_id').map((s) => s.spool_id)).toEqual([
      'FIL-002',
      'FIL-009',
      'FIL-010',
    ])
  })
})
