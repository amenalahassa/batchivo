/**
 * Product ideas and their timeline (spec 007), mirroring backend/app/schemas/idea.py.
 */

export type IdeaStatus =
  | 'inbox'
  | 'exploring'
  | 'validating'
  | 'ready'
  | 'converted'
  | 'parked'
  | 'dropped'

/** Statuses an operator can pick; `converted` is set only by a conversion. */
export type WritableIdeaStatus = Exclude<IdeaStatus, 'converted'>

export type IdeaSource = 'manual' | 'pain_point_report' | 'customer' | 'other'

export type EntryKind =
  | 'note'
  | 'image'
  | 'link'
  | 'sketch'
  | 'measurement'
  | 'decision'
  | 'generation'

export type TextEntryKind = 'note' | 'link' | 'measurement' | 'decision'
export type ImageEntryKind = 'image' | 'sketch'

export interface IdeaScores {
  frequency: number | null
  frustration: number | null
  printability: number | null
  gap: number | null
  willingness_to_pay: number | null
}

export type ScoreName = keyof IdeaScores

export interface UserRef {
  id: string
  name: string | null
}

export interface IdeaLink {
  id: string | null
  name: string | null
  sku: string | null
  state: 'linked' | 'gone' | 'none'
}

export interface IdeaSummary {
  id: string
  title: string
  status: IdeaStatus
  source: IdeaSource
  source_url: string | null
  tags: string[]
  scores: IdeaScores
  report_score: number | null
  score: number | null
  score_source: 'scores' | 'report' | null
  cover_thumbnail_path: string | null
  current_iteration: number
  archived: boolean
  model: IdeaLink
  product: IdeaLink
  created_at: string
  updated_at: string
}

export interface IdeaDetail extends IdeaSummary {
  summary: string | null
  cover_entry_id: string | null
  cover_image_path: string | null
  created_by: UserRef | null
}

export interface IdeaListParams {
  status?: IdeaStatus[]
  tag?: string[]
  source?: IdeaSource
  search?: string
  archived?: 'false' | 'true' | 'all'
  sort?: 'updated' | 'score' | 'created'
  skip?: number
  limit?: number
}

export interface IdeaListResponse {
  items: IdeaSummary[]
  total: number
  skip: number
  limit: number
}

export interface IdeaCreate {
  title: string
  summary?: string | null
  status?: WritableIdeaStatus
  source?: IdeaSource
  source_url?: string | null
  tags?: string[]
  scores?: Partial<IdeaScores>
  report_score?: number | null
}

export interface IdeaUpdate {
  title?: string
  summary?: string | null
  status?: WritableIdeaStatus
  source?: IdeaSource
  source_url?: string | null
  tags?: string[]
  scores?: Partial<IdeaScores>
  archived?: boolean
  cover_entry_id?: string | null
}

export interface IdeaEntry {
  id: string
  idea_id: string
  kind: EntryKind
  iteration: number
  body: string | null
  link_url: string | null
  pinned: boolean
  archived: boolean
  image_path: string | null
  thumbnail_path: string | null
  content_type: string | null
  original_filename: string | null
  file_size: number | null
  generation_job_id: string | null
  author: UserRef | null
  created_at: string
  edited_at: string | null
}

export interface IdeaEntryList {
  items: IdeaEntry[]
  current_iteration: number
}

export interface IdeaEntryCreate {
  kind: TextEntryKind
  body?: string | null
  link_url?: string | null
}

export interface IdeaEntryUpdate {
  body?: string | null
  link_url?: string | null
  pinned?: boolean
  archived?: boolean
  kind?: ImageEntryKind
}

export interface RefusedFile {
  filename: string | null
  reason: string
}

export interface ImageUploadResult {
  created: IdeaEntry[]
  refused: RefusedFile[]
}

export interface ConvertRequest {
  target: 'model' | 'product'
  name?: string
  model_sku?: string
  product_sku?: string
  include_images?: boolean
}

export interface ConvertResponse {
  idea: IdeaDetail
  model_id: string
  product_id: string | null
  copied_images: number
  warnings: string[]
}

export interface ImportItem {
  title: string
  summary?: string | null
  scores?: Partial<IdeaScores> | null
  report_score?: number | null
  tags?: string[]
  source_url?: string | null
}

export interface ImportResult {
  created: { id: string | null; title: string }[]
  skipped: { title: string; source_url: string | null; existing_idea_id: string | null }[]
  refused: { index: number; title: string | null; reason: string }[]
}

export interface ParseReportResponse {
  items: ImportItem[]
  warnings: string[]
}
