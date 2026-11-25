/**
 * Pure helpers of the Preflight screens (spec 009), kept apart from the
 * components so they can be tested on their own.
 */
import { PLACEHOLDER, type Calibration, type Intent, type Measurement } from '@/types/preflight'
import { blockText } from './preflightText'

// ============================================
// Intent (clarification Q4)
// ============================================

const FORM_KEYS = [
  'function',
  'category',
  'quantity',
  'selling',
  'sales_channel',
  'country',
  'success_criteria',
  'loads',
  'environment',
  'interfaces',
] as const

function indented(text: string): string {
  return text
    .split('\n')
    .map((line) => (line.trim() ? `  ${line}` : line))
    .join('\n')
}

/** The intent as YAML: the form's fields, the three text blocks, and every other key kept. */
export function composeIntentYaml(
  base: Intent | null,
  form: {
    function: string
    category: string
    quantity: string
    selling: boolean
    sales_channel: string
    country: string
    success_criteria: string
    loads: string
    environment: string
    interfaces: string
  }
): string {
  const kept: Record<string, unknown> = { schema_version: 1 }
  for (const [key, value] of Object.entries(base ?? {})) {
    if (!(FORM_KEYS as readonly string[]).includes(key)) kept[key] = value
  }
  const quantity = form.quantity.trim()
  const simple: Record<string, unknown> = {
    function: form.function.trim() || PLACEHOLDER,
    category: form.category.trim() || PLACEHOLDER,
    quantity: /^\d+$/.test(quantity) ? Number(quantity) : quantity || PLACEHOLDER,
    selling: form.selling,
    sales_channel: form.sales_channel,
    country: form.country.trim() || PLACEHOLDER,
    success_criteria: form.success_criteria
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
  }
  let text = blockText({ ...kept, ...simple })
  for (const key of ['loads', 'environment', 'interfaces'] as const) {
    const block = form[key].trim()
    if (block) text += `${key}:\n${indented(block)}\n`
  }
  return text
}


// ============================================
// Calibrations
// ============================================

export function comboKey(c: Calibration): string {
  return [c.material_type_id, c.filament_type_id ?? '', c.fit_type, c.orientation].join('|')
}

/** Combinations with their current value first, each with its history newest first. */
export function groupCalibrations(rows: Calibration[]): { current: Calibration; history: Calibration[] }[] {
  const groups = new Map<string, Calibration[]>()
  for (const row of rows) {
    const key = comboKey(row)
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups.values()]
    .map((items) => {
      const sorted = [...items].sort((a, b) => b.created_at.localeCompare(a.created_at))
      const current = sorted.find((c) => c.is_current) ?? sorted[0]
      return { current, history: sorted.filter((c) => c.id !== current.id) }
    })
    .sort((a, b) =>
      `${a.current.material_code}${a.current.fit_type}${a.current.orientation}`.localeCompare(
        `${b.current.material_code}${b.current.fit_type}${b.current.orientation}`
      )
    )
}


// ============================================
// Test results
// ============================================

export interface MeasurementRow {
  name: string
  value: string
  unit: string
}

export function measurementsOf(rows: MeasurementRow[]): Measurement[] {
  return rows
    .filter((row) => row.name.trim() || row.value.trim())
    .map((row) => ({
      name: row.name.trim(),
      value: row.value.trim(),
      ...(row.unit.trim() ? { unit: row.unit.trim() } : {}),
    }))
}

