// @vitest-environment node
/** Items per run and per-filament grams from a sliced file (spec 004, T066). */
import { describe, expect, it } from 'vitest'
import type { ThreeMFParseResponse, ThreeMFPlateInfo } from '@/lib/api/models'
import { itemsHint, parseItems, readWeightSuggestion, runFigures } from './threeMfFigures'

const plate = (index: number, extra: Partial<ThreeMFPlateInfo> = {}): ThreeMFPlateInfo => ({
  index,
  print_time_minutes: 60,
  filament_weight_grams: 10,
  ...extra,
})

const parse = (plates: ThreeMFPlateInfo[]): ThreeMFParseResponse => ({
  print_time_minutes: 60,
  filament_weight_grams: 10,
  plate_count: plates.length || null,
  source_plate_index: 1,
  slicer_detected: 'bambu_orca',
  thumbnail_available: false,
  plates,
})

describe('runFigures', () => {
  it('counts the objects on the chosen plates, not the plates', () => {
    const result = parse([plate(1, { object_count: 4 }), plate(2, { object_count: 4 }), plate(3, { object_count: 1 })])
    const figures = runFigures(result, new Set([1, 2]))
    expect(figures).toMatchObject({ plateCount: 2, itemCount: 8, printTimeMinutes: 120, weightGrams: 20 })
  })

  it('does not know the items when a chosen plate lists no objects', () => {
    const result = parse([plate(1, { object_count: 2 }), plate(2, { object_count: null })])
    expect(runFigures(result, new Set([1, 2])).itemCount).toBeNull()
    expect(runFigures(result, new Set([1])).itemCount).toBe(2)
  })

  it('does not know the items when the file lists no plates', () => {
    expect(runFigures(parse([]), new Set()).itemCount).toBeNull()
  })

  it('sums each filament over the plates by type and colour', () => {
    const result = parse([
      plate(1, { filaments: [{ type: 'PLA', color: '#FF0000', grams: 30.1 }, { type: 'PLA', color: '#000000', grams: 12 }] }),
      plate(2, { filaments: [{ type: 'PLA', color: '#FF0000', grams: 29.9 }] }),
    ])
    expect(runFigures(result, new Set([1, 2])).filaments).toEqual([
      { type: 'PLA', color: '#FF0000', grams: 60 },
      { type: 'PLA', color: '#000000', grams: 12 },
    ])
  })
})

describe('parseItems', () => {
  it.each([
    ['3', 3],
    [' 12 ', 12],
    ['0', null],
    ['1.5', null],
    ['-2', null],
    ['', null],
  ])('%j -> %j', (text, expected) => {
    expect(parseItems(text)).toBe(expected)
  })
})

describe('itemsHint', () => {
  it('shows one item\'s time and grams', () => {
    const figures = runFigures(parse([plate(1, { object_count: 3 })]), new Set([1]))
    expect(itemsHint(figures, '3')).toBe('3 objects on this plate in the file. Per item: 20m · 3.33g.')
  })
})

describe('readWeightSuggestion', () => {
  it('reads the JSON ModelForm writes', () => {
    const value = { total: 84, filaments: [{ type: 'PLA', color: '#FF0000', grams: 60 }] }
    expect(readWeightSuggestion(JSON.stringify(value))).toEqual(value)
  })

  it('still reads the plain number older code wrote', () => {
    expect(readWeightSuggestion('15.5')).toEqual({ total: 15.5, filaments: [] })
  })

  it('ignores anything else', () => {
    expect(readWeightSuggestion('not a weight')).toBeNull()
    expect(readWeightSuggestion('{"x":1}')).toBeNull()
  })
})
