/**
 * Labels and helpers of the Preflight screens (spec 009). Preflight's own
 * vocabulary (risk classes, value statuses) stays in French, as the skill
 * writes it; Batchivo's labels are in English.
 */
import axios from 'axios'

import { apiErrorDetail } from '@/lib/apiError'
import {
  PLACEHOLDER,
  type CalibrationProvenance,
  type FitType,
  type Orientation,
  type RiskClass,
  type StepName,
  type StepStatus,
  type TestKind,
  type TestOutcome,
} from '@/types/preflight'

export const STEP_TEXT: Record<StepName, string> = {
  intent: 'Intent',
  adopt: 'Adopt',
  clarify: 'Clarify',
  risk: 'Risk',
  plan: 'Plan',
  design: 'Design',
  check: 'Check',
  slice: 'Slice',
  print: 'Print',
  test: 'Test',
  learn: 'Learn',
  render: 'Render',
  ship: 'Ship',
  quick: 'Quick',
}

export const STEP_STATUS_TEXT: Record<StepStatus, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  done: 'Done',
  skipped: 'Skipped',
  blocked: 'Blocked',
}

export const STEP_STATUS_CLASS: Record<StepStatus, string> = {
  not_started: 'border-muted-foreground/30 text-muted-foreground',
  in_progress: 'border-sky-500 bg-sky-50 text-sky-900 dark:bg-sky-950 dark:text-sky-100',
  done: 'border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100',
  skipped: 'border-slate-400 bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  blocked: 'border-red-500 bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-100',
}

export const RISK_TEXT: Record<RiskClass, string> = {
  faible: 'faible (low)',
  moyen: 'moyen (medium)',
  élevé: 'élevé (high)',
  arrêt: 'arrêt (stop)',
}

export const FIT_TEXT: Record<FitType, string> = {
  slide: 'Slide',
  press: 'Press',
  snap: 'Snap',
  'print-in-place': 'Print-in-place',
}

export const ORIENTATION_TEXT: Record<Orientation, string> = {
  vertical: 'Vertical',
  horizontal: 'Horizontal',
}

export const PROVENANCE_TEXT: Record<CalibrationProvenance, string> = {
  measured: 'Measured',
  assumed: 'Assumed',
}

export const TEST_KIND_TEXT: Record<TestKind, string> = {
  clearance_grid: 'Clearance grid',
  critical_zone: 'Critical zone',
  full_part: 'Full part',
}

export const OUTCOME_TEXT: Record<TestOutcome, string> = {
  pass: 'Pass',
  fail: 'Fail',
  partial: 'Partial',
}

export const OUTCOME_CLASS: Record<TestOutcome, string> = {
  pass: 'border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100',
  fail: 'border-red-500 bg-red-50 text-red-900 dark:bg-red-950 dark:text-red-100',
  partial: 'border-amber-500 bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100',
}

/** Whether a value is still Preflight's "to clarify" placeholder. */
export function isPlaceholder(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'string' && value.includes(PLACEHOLDER))
}

/** A value as text: placeholders kept as written, objects in short YAML. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return blockText(value).trim()
  return String(value)
}

const RESERVED = /^(true|false|yes|no|on|off|null|~)$/i

function scalar(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value !== 'string') return String(value)
  // Plain only when YAML reads it back as the same string; otherwise JSON-quoted.
  const plain =
    /^[A-Za-zÀ-ÿ][\w .,°/()À-ÿ'-]*$/.test(value) && !RESERVED.test(value) && value.trim() === value
  return plain ? value : JSON.stringify(value)
}

const NL = '\n'

/**
 * A YAML-looking block for reading and for the editor's text areas (display
 * only: what is typed back is parsed by the server, the one YAML parser).
 */
export function blockText(value: unknown, indent = ''): string {
  if (Array.isArray(value)) {
    if (value.length === 0) return `${indent}[]${NL}`
    return value
      .map((item) =>
        item !== null && typeof item === 'object'
          ? `${indent}- ${blockText(item, `${indent}  `).trimStart()}`
          : `${indent}- ${scalar(item)}${NL}`
      )
      .join('')
  }
  if (value !== null && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return `${indent}{}${NL}`
    return entries
      .map(([key, item]) => {
        if (item !== null && typeof item === 'object') {
          const empty = Array.isArray(item) ? item.length === 0 : Object.keys(item).length === 0
          if (empty) return `${indent}${key}: ${Array.isArray(item) ? '[]' : '{}'}${NL}`
          return `${indent}${key}:${NL}${blockText(item, `${indent}  `)}`
        }
        return `${indent}${key}: ${scalar(item)}${NL}`
      })
      .join('')
  }
  return `${indent}${scalar(value)}${NL}`
}

/** A clearance as the API sent it ("0.150") read as "0.150 mm"; never through a float. */
export function mmText(value: string): string {
  return `${value} mm`
}

/** A decimal string the calibration API accepts: up to 3 decimals, 0 to 2. */
export function isValidClearance(text: string): boolean {
  const trimmed = text.trim()
  if (!/^\d(\.\d{1,3})?$/.test(trimmed)) return false
  const [whole, fraction = ''] = trimmed.split('.')
  return whole === '0' || whole === '1' || (whole === '2' && /^0*$/.test(fraction))
}

/**
 * A refused Preflight request as text. A validation failure keeps where it
 * failed (`intent_yaml.loads[0].duration: must be one of …`): an intent has
 * many nested values, and the message alone does not say which one is wrong.
 */
export function preflightErrorText(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (Array.isArray(detail) && detail.length > 0) {
      return detail
        .map((entry) => {
          const { loc, msg } = (entry ?? {}) as { loc?: unknown; msg?: unknown }
          const where = Array.isArray(loc) ? locText(loc) : ''
          return where ? `${where}: ${String(msg ?? '')}` : String(msg ?? '')
        })
        .join('; ')
    }
  }
  return apiErrorDetail(error)
}

function locText(loc: unknown[]): string {
  return loc
    .filter((part, index) => !(index === 0 && part === 'body'))
    .reduce<string>(
      (path, part) =>
        typeof part === 'number' ? `${path}[${part}]` : path ? `${path}.${String(part)}` : String(part),
      ''
    )
}
