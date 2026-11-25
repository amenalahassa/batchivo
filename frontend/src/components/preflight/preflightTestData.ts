/**
 * Briefs, calibrations and test results for the Preflight component tests (spec 009).
 */
import {
  PREFLIGHT_STEPS,
  type Calibration,
  type DesignBrief,
  type Intent,
  type PrintTestResult,
} from '@/types/preflight'

export const TEMPLATE_INTENT: Intent = {
  schema_version: 1,
  slug: '[À PRÉCISER]',
  function: '[À PRÉCISER]',
  category: '[À PRÉCISER]',
  images: [],
  loads: [
    {
      value: '[À PRÉCISER]',
      unit: 'kg',
      direction: '[À PRÉCISER]',
      duration: '[À PRÉCISER]',
      cycles: null,
      status: 'déduit',
    },
  ],
  environment: { max_temp_c: '[À PRÉCISER]', outdoor: false, status: 'déduit' },
  interfaces: [{ neighbour: '[À PRÉCISER]', fit: '[À PRÉCISER]', dimensions_mm: {}, status: 'estimée' }],
  quantity: 1,
  selling: false,
  sales_channel: 'none',
  country: '[À PRÉCISER]',
  success_criteria: ['[À PRÉCISER]'],
  x_custom: { kept: true },
}

export function aBrief(overrides: Partial<DesignBrief> = {}): DesignBrief {
  return {
    id: 'brief-1',
    idea_id: 'idea-1',
    model_id: null,
    idea_title: 'Porte-sac',
    model_name: null,
    intent: null,
    intent_schema_version: null,
    risk_class: null,
    risk_md: null,
    triage: null,
    plan_md: null,
    params: null,
    params_updated_at: null,
    steps: PREFLIGHT_STEPS.map((step) => ({ step, status: 'not_started', updated_at: null, updated_by: null })),
    validation: { to_clarify: [], unconfirmed: [], missing: [] },
    revision_counts: { intent: 0, risk: 0, plan: 0 },
    created_by: { id: 'u', name: 'Konrad' },
    updated_by: { id: 'u', name: 'Konrad' },
    created_at: '2026-11-25T10:00:00Z',
    updated_at: '2026-11-25T10:00:00Z',
    ...overrides,
  }
}

export function aCalibration(overrides: Partial<Calibration> = {}): Calibration {
  return {
    id: 'cal-1',
    printer_id: 'printer-1',
    printer_name: 'A1',
    material_type_id: 'pla',
    material_code: 'PLA',
    filament_type_id: null,
    filament_label: null,
    orientation: 'vertical',
    fit_type: 'slide',
    value_mm: '0.150',
    provenance: 'measured',
    source_print_job_id: null,
    source_test_result_id: null,
    measured_at: '2026-11-20T10:00:00Z',
    notes: null,
    recorded_by: { id: 'u', name: 'Konrad' },
    superseded_by_id: null,
    superseded_at: null,
    is_current: true,
    created_at: '2026-11-20T10:00:00Z',
    ...overrides,
  }
}

export function aTestResult(overrides: Partial<PrintTestResult> = {}): PrintTestResult {
  return {
    id: 'result-1',
    kind: 'critical_zone',
    outcome: 'fail',
    model_id: 'model-1',
    model_name: 'Porte-sac',
    model_file_version_id: 'v1',
    version_label: '1',
    print_job_id: null,
    printer_id: null,
    material_type_id: 'pla',
    material_code: 'PLA',
    filament_type_id: null,
    orientation: 'horizontal',
    measurements: [{ name: 'load_kg', value: 7, unit: 'kg', expected: 5 }],
    failure_mode: 'broke at the root at 7 kg',
    notes: null,
    photo_available: false,
    recorded_by: { id: 'u', name: 'Konrad' },
    updated_by: { id: 'u', name: 'Konrad' },
    created_at: '2026-11-24T10:00:00Z',
    updated_at: '2026-11-24T10:00:00Z',
    ...overrides,
  }
}
