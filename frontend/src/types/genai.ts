/**
 * Generative AI layer types (spec 008, contracts/genai-api.md).
 *
 * Every amount is a decimal string in US dollars: never a JavaScript number.
 */

export type Capability =
  | 'concept_image'
  | 'image_edit'
  | 'product_photo_enhance'
  | 'background_remove'
  | 'upscale'
  | 'lifestyle_scene'
  | 'image_to_3d'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
export type TargetType = 'idea' | 'product' | 'model' | 'none'
export type TokenSource = 'tenant' | 'platform' | 'none'
export type PriceUnit = 'per_output' | 'per_run' | 'per_second'
export type AssetRefType = 'asset' | 'idea_entry' | 'product_image' | 'model_image'

export interface AssetRef {
  type: AssetRefType
  id: string
}

export interface JobTarget {
  type: TargetType
  id?: string | null
}

export interface JobInputs {
  prompt?: string
  style?: string
  instruction?: string
  scene?: string
  count?: number
  factor?: 2 | 4
  seed?: number
  input_assets?: AssetRef[]
}

export interface GenerationJobCreate {
  capability: Capability
  inputs: JobInputs
  target?: JobTarget
}

export interface PriceInfo {
  unit: PriceUnit
  amount_usd: string
  source: string
  assumed: boolean
}

export interface AdoptionInfo {
  owner_type: 'idea' | 'product' | 'model'
  owner_id: string
  idea_entry_id: string | null
  product_image_id: string | null
  model_file_id: string | null
  warning_confirmed: boolean
  created_at: string
}

export interface GenAIAsset {
  id: string
  job_id: string | null
  source: 'output' | 'upload'
  kind: 'image' | 'mesh'
  content_type: string
  file_size: number
  width: number | null
  height: number | null
  position: number
  original_filename: string | null
  ai_generated: boolean
  file_path: string
  thumbnail_path: string | null
  adoptions: AdoptionInfo[]
  created_at: string
}

export interface GenerationJob {
  id: string
  capability: Capability
  capability_label: string
  provider: string
  model_ref: string
  model_version: string
  model_version_ran: string | null
  inputs: Record<string, unknown>
  seed: number
  target: JobTarget
  status: JobStatus
  error: string | null
  error_code: string | null
  estimated_cost: string
  cost: string | null
  cost_provenance: 'computed' | 'estimated' | null
  currency: string
  price: PriceInfo
  shows_real_item: boolean
  requested_by: { id: string; name: string | null } | null
  created_at: string
  submitted_at: string | null
  started_at: string | null
  completed_at: string | null
  outputs: GenAIAsset[]
  can_cancel: boolean
}

export interface GenerationJobList {
  items: GenerationJob[]
  total: number
}

export interface JobListParams {
  target_type?: TargetType
  target_id?: string
  status?: JobStatus
  capability?: Capability
  skip?: number
  limit?: number
}

/** One input's rules as `GET /capabilities` reports them (contract `inputs{}`). */
export interface CapabilityInputRule {
  required?: boolean
  max_length?: number
  min?: number
  max?: number
  default?: number
  /** For `count`: the most a run makes once input images are picked. */
  max_with_inputs?: number
  values?: (string | number)[]
}

export interface CapabilityInfo {
  capability: Capability
  label: string
  output_kind: 'image' | 'mesh'
  model_ref: string
  model_version: string
  pinnable: boolean
  overridden: boolean
  price: PriceInfo
  max_count: number
  max_inputs: number
  /** Input rules by field (`prompt`, `count`, `input_assets`…); older servers omit it. */
  inputs?: Record<string, CapabilityInputRule>
  time_limit_s: number
  shows_real_item: boolean
}

export interface CapabilitiesResponse {
  connected: boolean
  token_source: TokenSource
  currency: string
  capabilities: CapabilityInfo[]
}

export interface EstimateResponse {
  estimated_cost: string
  month_to_date: string
  budget: string | null
  would_exceed_budget: boolean
  currency: string
}

export interface AdoptRequest {
  target: JobTarget
  confirm_not_real_item?: boolean
  alt_text?: string
  version_note?: string
}

export interface AdoptResponse {
  adoption: AdoptionInfo
  idea_entry_id: string | null
  product_image_id: string | null
  model_file_id: string | null
  model_file_version_id: string | null
}

export interface ReplicateModelOverride {
  model_ref: string
  model_version: string
  price_unit?: PriceUnit | null
  price_usd?: string | null
  /** How long a run usually takes, in seconds, to estimate a per-second price. */
  typical_seconds?: number | null
}

export interface ReplicateSettings {
  is_configured: boolean
  token_masked: string | null
  token_source: TokenSource
  platform_token_available: boolean
  platform_token_allowed: boolean
  monthly_budget: string | null
  currency: string
  month_to_date: string
  jobs_this_month: number
  active_jobs: number
  concurrency_limit: number
  model_overrides: Partial<Record<Capability, ReplicateModelOverride>>
  updated_at: string | null
}

export interface ReplicateSettingsUpdate {
  api_token?: string
  monthly_budget?: string
  clear_budget?: boolean
  model_overrides?: Partial<Record<Capability, ReplicateModelOverride | null>>
}

export interface ReplicateConnectionTest {
  success: boolean
  message: string
  account: string | null
  token_source: TokenSource
}

export interface ReplicateUsage {
  currency: string
  months: { month: string; cost: string; jobs: number }[]
}

export interface PlatformGenaiSettings {
  tenant_id: string
  platform_token_allowed: boolean
  platform_token_available: boolean
  all_tenants: boolean
}

/** The `detail` of a refused request: `{code, message}`. */
export interface GenAIErrorDetail {
  code: string
  message: string
}
