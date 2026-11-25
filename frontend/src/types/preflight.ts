/**
 * Preflight foundations (spec 009): design briefs, fit calibrations and print
 * test results. Mirrors `backend/app/schemas/design_brief.py`,
 * `calibration.py` and `print_test_result.py`.
 *
 * `value_mm` is a decimal string (exact to the micron), never a JS number.
 */
import type { PersonRef } from './model-file-version'

export const PREFLIGHT_STEPS = [
  'intent',
  'adopt',
  'clarify',
  'risk',
  'plan',
  'design',
  'check',
  'slice',
  'print',
  'test',
  'learn',
  'render',
  'ship',
  'quick',
] as const
export type StepName = (typeof PREFLIGHT_STEPS)[number]

export const STEP_STATUSES = ['not_started', 'in_progress', 'done', 'skipped', 'blocked'] as const
export type StepStatus = (typeof STEP_STATUSES)[number]

export const RISK_CLASSES = ['faible', 'moyen', 'élevé', 'arrêt'] as const
export type RiskClass = (typeof RISK_CLASSES)[number]

export type RevisionPart = 'intent' | 'risk' | 'plan'

/** The placeholder Preflight writes for an unknown value. */
export const PLACEHOLDER = '[À PRÉCISER]'

export const VALUE_STATUSES = ['déduit', 'estimée', 'validé', 'mesurée'] as const
export type ValueStatus = (typeof VALUE_STATUSES)[number]

export const SALES_CHANNELS = ['etsy', 'makerworld', 'shop', 'none'] as const

/** Preflight's `intent.yaml`, kept as written: known keys typed, the rest passed through. */
export interface Intent {
  schema_version?: number
  slug?: string
  function?: string
  category?: string
  images?: string[]
  loads?: Record<string, unknown>[]
  environment?: Record<string, unknown>
  interfaces?: Record<string, unknown>[]
  quantity?: number | string
  selling?: boolean
  sales_channel?: string
  country?: string
  eu?: boolean
  third_party_model?: boolean
  third_party_license?: string | null
  alternatives?: string
  success_criteria?: string[]
  [key: string]: unknown
}

export interface StepState {
  step: StepName
  status: StepStatus
  updated_at: string | null
  updated_by: PersonRef | null
}

export interface IntentValidation {
  to_clarify: string[]
  unconfirmed: { field: string; status: string }[]
  missing: string[]
}

export interface RiskPart {
  risk_class?: RiskClass | null
  risk_md?: string | null
  triage?: Record<string, unknown> | null
}

export interface DesignBrief {
  id: string
  idea_id: string | null
  model_id: string | null
  idea_title: string | null
  model_name: string | null
  intent: Intent | null
  intent_schema_version: number | null
  risk_class: RiskClass | null
  risk_md: string | null
  triage: Record<string, unknown> | null
  plan_md: string | null
  params: Record<string, unknown> | null
  params_updated_at: string | null
  steps: StepState[]
  validation: IntentValidation
  revision_counts: Record<RevisionPart, number>
  created_by: PersonRef | null
  updated_by: PersonRef | null
  created_at: string
  updated_at: string
}

export interface DesignBriefStart {
  intent?: Intent
  intent_yaml?: string
}

export interface DesignBriefUpdate extends DesignBriefStart {
  risk?: RiskPart
  plan_md?: string | null
  params?: Record<string, unknown>
  params_yaml?: string
  steps?: Partial<Record<StepName, StepStatus>>
}

export interface DesignBriefUpdateResult extends DesignBrief {
  created_revisions: RevisionPart[]
}

export interface DesignBriefRevision {
  id: string
  part: RevisionPart
  content: Record<string, unknown>
  schema_version: number | null
  author: PersonRef | null
  created_at: string
}

// ============================================
// Calibrations
// ============================================

export const FIT_TYPES = ['slide', 'press', 'snap', 'print-in-place'] as const
export type FitType = (typeof FIT_TYPES)[number]
export const ORIENTATIONS = ['vertical', 'horizontal'] as const
export type Orientation = (typeof ORIENTATIONS)[number]
export type CalibrationProvenance = 'measured' | 'assumed'

export interface Calibration {
  id: string
  printer_id: string
  printer_name: string | null
  material_type_id: string
  material_code: string | null
  filament_type_id: string | null
  filament_label: string | null
  orientation: Orientation
  fit_type: FitType
  /** Clearance per side, mm, as a decimal string ("0.150"). */
  value_mm: string
  provenance: CalibrationProvenance
  source_print_job_id: string | null
  source_test_result_id: string | null
  measured_at: string
  notes: string | null
  recorded_by: PersonRef | null
  superseded_by_id: string | null
  superseded_at: string | null
  is_current: boolean
  created_at: string
}

export interface CalibrationCreate {
  material_type_id?: string
  material?: string
  filament_type_id?: string | null
  orientation: Orientation
  fit_type: FitType
  /** Sent as a string so the value stays exact. */
  value_mm: string
  provenance: CalibrationProvenance
  source_print_job_id?: string | null
  source_test_result_id?: string | null
  measured_at?: string | null
  notes?: string | null
}

// ============================================
// Print test results
// ============================================

export const TEST_KINDS = ['clearance_grid', 'critical_zone', 'full_part'] as const
export type TestKind = (typeof TEST_KINDS)[number]
export const TEST_OUTCOMES = ['pass', 'fail', 'partial'] as const
export type TestOutcome = (typeof TEST_OUTCOMES)[number]

export interface Measurement {
  name?: string
  value?: unknown
  unit?: string
  expected?: unknown
  [key: string]: unknown
}

export interface PrintTestResult {
  id: string
  kind: TestKind
  outcome: TestOutcome
  model_id: string | null
  model_name: string | null
  model_file_version_id: string | null
  version_label: string | null
  print_job_id: string | null
  printer_id: string | null
  material_type_id: string | null
  material_code: string | null
  filament_type_id: string | null
  orientation: Orientation | null
  measurements: Measurement[]
  failure_mode: string | null
  notes: string | null
  photo_available: boolean
  recorded_by: PersonRef | null
  updated_by: PersonRef | null
  created_at: string
  updated_at: string
}

export interface PrintTestResultCreate {
  kind: TestKind
  outcome: TestOutcome
  model_id?: string | null
  model_file_version_id?: string | null
  print_job_id?: string | null
  printer_id?: string | null
  material_type_id?: string | null
  material?: string | null
  filament_type_id?: string | null
  orientation?: Orientation | null
  measurements?: Measurement[]
  failure_mode?: string | null
  notes?: string | null
}

export interface PrintTestResultUpdate {
  outcome?: TestOutcome
  measurements?: Measurement[]
  failure_mode?: string | null
  notes?: string | null
}

export interface PrintTestResultList {
  items: PrintTestResult[]
  total: number
}

export interface PrintTestResultParams {
  model_id?: string
  model_file_version_id?: string
  print_job_id?: string
  printer_id?: string
  outcome?: TestOutcome
  kind?: TestKind
  skip?: number
  limit?: number
}
