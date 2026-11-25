/**
 * Model file versions, the activation review and pinned notes (spec 004,
 * contracts/api.md). Mirrors `app/schemas/model_file_version.py` and
 * `app/schemas/model_file_note.py`.
 */
import type { ModelFile } from '@/lib/api/models'

export interface PersonRef {
  id: string
  name: string
}

export interface FileVersion {
  id: string
  model_id: string
  sequence: number
  label: string
  note: string | null
  is_active: boolean
  /** The sliced file whose figures feed the cost profile (clarification Q1). */
  print_file_id: string | null
  created_by: PersonRef | null
  created_at: string
  files: ModelFile[]
  /** Whether any file of the version has been measured (FR-013). */
  has_measurable_file: boolean
  open_note_count: number
}

/** Grams per bill-of-materials line, keyed by its name ("PLA Red"). */
export type LineGrams = Record<string, string>

/** A per-line weight proposal: by line id for the write, by name for the screen. */
export interface LineWeights {
  lines: Record<string, string>
  labels: LineGrams
}

export type ActivationField = 'print_time_minutes' | 'prints_per_plate' | 'weight_grams' | 'dimensions'

export interface DimensionsValue {
  length_mm: string | null
  width_mm: string | null
  height_mm: string | null
  /** Where the current figure came from (`entered`, `measured`, ...). */
  source?: string
}

/** One figure the activation would change, from what to what. */
export interface ActivationRow {
  field: ActivationField
  target: 'model' | 'model_printer_config' | 'model_material' | 'dimensions'
  /** Per-line grams of a several-material bill of materials: name -> grams (T067). */
  current: string | DimensionsValue | LineGrams | null
  proposed: string | DimensionsValue | LineWeights | null
  selectable: boolean
  /** Why the row cannot be applied, when it cannot. */
  reason: string | null
  source_file_id: string | null
}

export interface ActivationPreview {
  version_id: string
  print_file_id: string | null
  dimension_file_id: string | null
  dimension_file_name: string | null
  rows: ActivationRow[]
  notices: string[]
}

export type NoteStatus = 'open' | 'resolved' | 'carried_forward' | 'dismissed'

/** Who raised a note (spec 009): a person, Preflight's check, a printer or the slicer. */
export type NoteSource = 'person' | 'preflight' | 'printer' | 'slicer'
export type NoteSeverity = 'info' | 'warning' | 'failure'

/** Spec 009 type fields; a note written without them reads as a person's "info" note. */
export interface NoteTypeFields {
  source?: NoteSource
  rule_id?: string | null
  severity?: NoteSeverity
  /** A decimal string, kept exactly as sent (spec 009). */
  measured_value?: string | null
  expected_value?: string | null
  value_unit?: string | null
}

export type Vector3 = [number, number, number]

export interface FileNote {
  id: string
  number: number
  model_file_id: string | null
  version_id: string
  position: Vector3
  normal: Vector3
  layer: number | null
  text: string
  status: NoteStatus
  resolved_in_version_id: string | null
  carried_to_version_id: string | null
  carried_from_note_id: string | null
  author: PersonRef | null
  created_at: string
  archived_at: string | null
  /** An open note of an earlier version, shown faded on a newer file (FR-029). */
  ghost: boolean
  source: NoteSource
  rule_id: string | null
  severity: NoteSeverity
  measured_value: string | null
  expected_value: string | null
  value_unit: string | null
  /** Why a dismissed note was set aside; kept when it is reopened (spec 009 Q2). */
  dismissal_reason: string | null
  dismissed_at: string | null
  dismissed_by: PersonRef | null
}

export interface NoteCreate extends NoteTypeFields {
  position: Vector3
  normal: Vector3
  layer?: number | null
  text: string
}

export interface NoteUpdate extends NoteTypeFields {
  text?: string
  position?: Vector3
  normal?: Vector3
  status?: 'open' | 'resolved' | 'dismissed'
  resolved_in_version_id?: string | null
  /** Required with status "dismissed". */
  dismissal_reason?: string
}
