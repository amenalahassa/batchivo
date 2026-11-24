/**
 * Types for sending a print to a Bambu printer (spec 011).
 *
 * Mirrors backend/app/schemas/print_send.py. Grams are decimal strings.
 */

export type SlotRef =
  | { kind: 'ams'; ams_id: number; tray_id: number }
  | { kind: 'external' }

export interface AmsMappingEntry {
  filament_id: number
  slot: SlotRef
}

export interface SlotView {
  kind: 'ams' | 'external'
  ams_id: number | null
  tray_id: number | null
  label: string
}

export interface PrintSendLine {
  filament_id: number
  expected: { type: string | null; color: string | null; grams: string | null }
  slot: SlotView
  mapped_spool: {
    id: string
    spool_id: string
    material: string | null
    color: string | null
    current_weight: string | null
  } | null
  reported: { type: string | null; color: string | null; present: boolean } | null
  warnings: string[]
}

export interface PrintSendWarning {
  code: string
  message: string
  filament_id: number | null
}

export interface PrintSendSummary {
  id: string
  status: 'prepared' | 'confirming' | 'started' | 'transfer_failed' | 'start_failed'
  expires_at: string
  printer: { id: string; name: string }
  file: { name: string; model_id: string | null; model_file_id: string | null }
  plate: { index: number; print_time_minutes: number | null; filament_weight_grams: string | null }
  lines: PrintSendLine[]
  warnings: PrintSendWarning[]
  blockers: PrintSendWarning[]
  requires_acknowledgement: boolean
}

export interface PrintSendPrepared extends PrintSendSummary {
  confirmation_token: string
}

export interface ConsumptionLine {
  filament_id: number
  spool_id: string | null
  proposed_grams: string
  accepted_grams: string | null
  transaction_id: string | null
}

export interface PrintSend extends PrintSendSummary {
  created_at: string
  confirmed_at: string | null
  /** Who confirmed the send (FR-018). */
  confirmed_by?: { id: string; name: string } | null
  warnings_acknowledged: boolean
  error_message: string | null
  print_job: {
    id: string
    status: string
    started_at: string | null
    completed_at: string | null
  } | null
  consumption: {
    status: 'none' | 'pending' | 'accepted' | 'dismissed'
    lines: ConsumptionLine[]
    decided_at: string | null
  }
}

export interface PreparePrintSendInput {
  plate: number
  mapping: AmsMappingEntry[]
  file?: File
  modelFileId?: string
  attachToModelId?: string
}

export interface ConsumptionAcceptLine {
  filament_id: number
  spool_id: string
  grams: string
}

export interface FileTransferTestResult {
  ok: boolean
  message: string
}
