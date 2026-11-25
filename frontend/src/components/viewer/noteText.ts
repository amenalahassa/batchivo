/**
 * A note's status and type as the operator reads them (spec 004 FR-027, spec 009 US2).
 */
import type { FileNote, NoteSeverity, NoteSource } from '@/types/model-file-version'

export function statusText(note: FileNote): string {
  if (note.status === 'resolved') return 'Resolved'
  if (note.status === 'carried_forward') return 'Carried forward'
  if (note.status === 'dismissed') return 'Dismissed'
  return 'Open'
}

export const SEVERITY_TEXT: Record<NoteSeverity, string> = {
  info: 'Info',
  warning: 'Warning',
  failure: 'Failure',
}

export const SOURCE_TEXT: Record<NoteSource, string> = {
  person: 'Person',
  preflight: 'Preflight',
  printer: 'Printer',
  slicer: 'Slicer',
}

/** Badge classes per severity; "info" stays neutral so untyped notes look as before. */
export const SEVERITY_CLASS: Record<NoteSeverity, string> = {
  info: '',
  warning: 'border-amber-500 bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  failure: 'border-red-500 bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
}

/** "0.6 mm (expected 0.9 mm)", or null when the note carries no measure. */
export function measureText(note: FileNote): string | null {
  const unit = note.value_unit ? ` ${note.value_unit}` : ''
  if (note.measured_value === null && note.expected_value === null) return null
  if (note.expected_value === null) return `${note.measured_value}${unit}`
  if (note.measured_value === null) return `expected ${note.expected_value}${unit}`
  return `${note.measured_value}${unit} (expected ${note.expected_value}${unit})`
}

/** Whether the note carries anything beyond a person's plain note. */
export function isTyped(note: FileNote): boolean {
  return note.source !== 'person' || note.severity !== 'info' || note.rule_id !== null
}
