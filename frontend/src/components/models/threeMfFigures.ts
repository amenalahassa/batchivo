/**
 * What the chosen plates of a sliced file say about one print run (spec 004, T066).
 *
 * The cost engine reads a model's plate time and bill-of-materials grams as one
 * run, divided by "Items per Plate". So the plates chosen form one run, and the
 * items it makes are the objects on those plates, never the number of plates:
 * two plates may make one item (a body and its base) or eight.
 *
 * Display only: nothing here is a price, and the figures go to the form as the
 * operator confirms them.
 */
import type { ThreeMFFilamentUse, ThreeMFParseResponse } from '@/lib/api/models'

export interface RunFilament {
  type: string | null
  color: string | null
  grams: number
}

export interface RunFigures {
  printTimeMinutes: number | null
  weightGrams: number | null
  plateCount: number | null
  /** Objects on the chosen plates; null when any of them does not list its objects. */
  itemCount: number | null
  /** Grams per filament over the run, summed by type and colour. */
  filaments: RunFilament[]
}

/** What ModelForm hands BOMEditor through sessionStorage. */
export interface WeightSuggestion {
  total: number
  filaments: RunFilament[]
}

const round2 = (n: number) => Math.round(n * 100) / 100

function sum(values: (number | null | undefined)[]): number | null {
  const present = values.filter((v): v is number => v != null)
  return present.length > 0 ? round2(present.reduce((a, b) => a + b, 0)) : null
}

function sumFilaments(uses: ThreeMFFilamentUse[]): RunFilament[] {
  const byKey = new Map<string, RunFilament>()
  for (const use of uses) {
    if (use.grams == null) continue
    const key = `${use.type ?? ''}|${use.color ?? ''}`
    const known = byKey.get(key)
    if (known) known.grams = round2(known.grams + use.grams)
    else byKey.set(key, { type: use.type, color: use.color, grams: round2(use.grams) })
  }
  return [...byKey.values()]
}

export function runFigures(result: ThreeMFParseResponse, selected: Set<number>): RunFigures {
  const plates = result.plates.length > 1 ? result.plates.filter((p) => selected.has(p.index)) : result.plates
  if (plates.length === 0) {
    return {
      printTimeMinutes: result.plates.length > 1 ? null : result.print_time_minutes,
      weightGrams: result.plates.length > 1 ? null : result.filament_weight_grams,
      plateCount: result.plates.length > 1 ? null : result.plate_count,
      itemCount: null,
      filaments: [],
    }
  }
  const counts = plates.map((p) => p.object_count)
  return {
    printTimeMinutes:
      result.plates.length > 1 ? sum(plates.map((p) => p.print_time_minutes)) : result.print_time_minutes,
    weightGrams:
      result.plates.length > 1 ? sum(plates.map((p) => p.filament_weight_grams)) : result.filament_weight_grams,
    plateCount: plates.length,
    itemCount: counts.every((c) => c != null && c > 0) ? counts.reduce((a, b) => a! + b!, 0)! : null,
    filaments: sumFilaments(plates.flatMap((p) => p.filaments ?? [])),
  }
}

/** A positive whole number of items, or null. */
export function parseItems(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null
  const n = Number(text.trim())
  return n > 0 ? n : null
}

export function filamentLabel(f: { type: string | null; color: string | null }): string {
  return [f.type, f.color].filter(Boolean).join(' ') || 'Filament'
}

/** Read what ModelForm stored: the new JSON shape, or the plain number older code wrote. */
export function readWeightSuggestion(stored: string): WeightSuggestion | null {
  try {
    const parsed: unknown = JSON.parse(stored)
    if (typeof parsed === 'number') return Number.isFinite(parsed) ? { total: parsed, filaments: [] } : null
    if (parsed && typeof parsed === 'object' && typeof (parsed as WeightSuggestion).total === 'number') {
      const value = parsed as WeightSuggestion
      return { total: value.total, filaments: Array.isArray(value.filaments) ? value.filaments : [] }
    }
  } catch {
    // not JSON: fall through to a plain number
  }
  const n = parseFloat(stored)
  return Number.isNaN(n) ? null : { total: n, filaments: [] }
}

export function formatPrintTime(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours === 0) return `${mins}m`
  if (mins === 0) return `${hours}h`
  return `${hours}h ${mins}m`
}

/** The line under the items question: where the default came from, and what one item costs in time and grams. */
export function itemsHint(figures: RunFigures, itemsText: string): string {
  const where =
    figures.itemCount != null
      ? `${figures.itemCount} object${figures.itemCount === 1 ? '' : 's'} on ${
          figures.plateCount === 1 ? 'this plate' : `${figures.plateCount} plates`
        } in the file.`
      : "The file doesn't say how many objects it prints: enter the items yourself."
  const items = parseItems(itemsText)
  if (items == null) return where
  const parts = [
    figures.printTimeMinutes != null ? formatPrintTime(Math.round(figures.printTimeMinutes / items)) : null,
    figures.weightGrams != null ? `${round2(figures.weightGrams / items)}g` : null,
  ].filter(Boolean)
  return parts.length ? `${where} Per item: ${parts.join(' · ')}.` : where
}
