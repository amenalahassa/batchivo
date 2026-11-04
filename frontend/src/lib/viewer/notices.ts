/**
 * What the viewer tells the operator about a file (spec 004, FR-021 to FR-023).
 */
import type { GcodeHeader } from './gcode'
import type { Printer } from '@/types/printer'

export const LOCAL_REFERENCE_TEXT =
  "This file is linked from a path on your computer, not uploaded, so it can't be opened here. Upload it to view it."
export const NO_PLANNED_MACHINE =
  'No planned machine: set a planned printer in the cost profile to see its bed.'
export const REDUCED_PREVIEW = 'Reduced preview: large file. Some lines or triangles are not drawn.'

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')

/** What the file says it was sliced for, where it differs from the plan (FR-021). */
export function mismatches(
  header: GcodeHeader,
  printer: Pick<Printer, 'name' | 'model' | 'nozzle_diameter_mm'> | null,
  materialCodes: string[]
): string[] {
  const out: string[] = []
  if (header.printerModel && printer) {
    const sliced = norm(header.printerModel)
    const names = [printer.model, printer.name].filter(Boolean).map((n) => norm(n as string))
    if (!names.some((n) => n && (sliced.includes(n) || n.includes(sliced)))) {
      out.push(`Sliced for ${header.printerModel}; the planned printer is ${printer.name}.`)
    }
  }
  if (header.filamentType && materialCodes.length > 0) {
    const sliced = norm(header.filamentType)
    if (!materialCodes.some((c) => sliced.startsWith(norm(c)) || norm(c).startsWith(sliced))) {
      out.push(`Sliced for ${header.filamentType}; the bill of materials uses ${[...new Set(materialCodes)].join(', ')}.`)
    }
  }
  if (header.nozzleDiameter && printer?.nozzle_diameter_mm) {
    const sliced = Number(header.nozzleDiameter)
    if (Number.isFinite(sliced) && Math.abs(sliced - Number(printer.nozzle_diameter_mm)) > 0.001) {
      out.push(
        `Sliced for a ${header.nozzleDiameter} mm nozzle; the planned printer has ${printer.nozzle_diameter_mm} mm.`
      )
    }
  }
  return out
}
