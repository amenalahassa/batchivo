/**
 * TypeScript types for Printer system
 *
 * Mirrors the backend Pydantic schemas for type safety
 */

/**
 * Base printer fields
 */
export interface PrinterBase {
  name: string;
  manufacturer?: string | null;
  model?: string | null;
  serial_number?: string | null;
  bed_size_x_mm?: number | null;
  bed_size_y_mm?: number | null;
  bed_size_z_mm?: number | null;
  nozzle_diameter_mm?: number | null;
  default_bed_temp?: number | null;
  default_nozzle_temp?: number | null;
  capabilities?: Record<string, unknown> | null;
  notes?: string | null;
  is_active?: boolean;
}

/**
 * Printer creation payload
 */
export type PrinterCreate = PrinterBase

/**
 * Printer update payload (all fields optional)
 */
export type PrinterUpdate = Partial<PrinterBase>

/**
 * Printer response from API
 */
export interface Printer extends PrinterBase {
  id: string;
  tenant_id: string;
  created_at: string;
  updated_at: string;
}

/**
 * Paginated list response for printers
 */
export interface PrinterListResponse {
  printers: Printer[];
  total: number;
  skip: number;
  limit: number;
}

/**
 * Filters for listing printers
 */
export interface PrinterFilters {
  is_active?: boolean;
  skip?: number;
  limit?: number;
}

/**
 * Printer summary for embedding in other responses
 */
export interface PrinterSummary {
  id: string;
  name: string;
  manufacturer?: string | null;
  model?: string | null;
}

/**
 * Known printer model from the registry
 */
export interface PrinterModelInfo {
  model_key: string;
  display_name: string;
  manufacturer: string;
  connection_type: string;
  has_toolhead_changer: boolean;
  has_ams: boolean;
}

/**
 * Printer status values from adapters / WebSocket
 */
export type PrinterStatus = 'printing' | 'paused' | 'error' | 'idle' | 'offline';

/**
 * AMS slot state (single slot in a multi-colour system)
 */
export interface AMSSlot {
  slot_index: number;
  filament_type?: string | null;
  colour_hex?: string | null;
  is_loaded: boolean;
}

/**
 * Live printer state broadcast over WebSocket
 */
export interface PrinterLiveState {
  id: string;
  name: string;
  model?: string | null;
  status: PrinterStatus;
  job_name?: string | null;
  progress_percent?: number | null;
  eta_seconds?: number | null;
  last_seen_at?: string | null;
  ams_slots: AMSSlot[];
  active_toolhead?: string | null;
}

/**
 * WebSocket message from /ws/printers
 */
export interface PrinterStateMessage {
  type: 'printer_state';
  data: PrinterLiveState[];
}

/**
 * Printer connection settings (Bambu LAN, Moonraker, ...)
 *
 * The access code is masked in responses; send it only when the operator
 * types a new one.
 */
export type SecretState = 'set' | 'unset' | 'unreadable';

export interface PrinterConnection {
  id: string;
  printer_id: string;
  connection_type: string;
  serial_number?: string | null;
  ip_address?: string | null;
  port: number;
  access_code?: string | null;
  /**
   * Spec 009: secrets are stored encrypted. "unreadable" means a stored value
   * the server key can no longer decrypt; the operator must enter it again.
   */
  access_code_state?: SecretState;
  cloud_token_state?: SecretState;
  ams_count: number;
  is_enabled: boolean;
  /** Operator-declared Bambu Developer Mode (spec 011). */
  developer_mode: boolean;
  /** Developer Mode on a Bambu LAN connection: prints can be sent. */
  can_send_prints: boolean;
  is_connected: boolean;
  connection_error?: string | null;
}

export interface PrinterConnectionSave {
  connection_type: string;
  serial_number?: string | null;
  ip_address?: string | null;
  access_code?: string;
  ams_count?: number;
  developer_mode: boolean;
}
