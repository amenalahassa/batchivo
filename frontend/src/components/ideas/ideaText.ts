/**
 * Words for ideas: statuses, sources, entry kinds and scores (spec 007).
 */
import type {
  EntryKind,
  IdeaEntry,
  IdeaSource,
  IdeaStatus,
  IdeaSummary,
  ImportItem,
  ImportResult,
  ScoreName,
  WritableIdeaStatus,
} from '@/types/idea'

/** Board columns, in the order an idea matures; converted last. */
export const BOARD_STATUSES: IdeaStatus[] = [
  'inbox',
  'exploring',
  'validating',
  'ready',
  'parked',
  'dropped',
  'converted',
]

/** What an operator may pick; `converted` comes only from a conversion (FR-007). */
export const WRITABLE_STATUSES: WritableIdeaStatus[] = [
  'inbox',
  'exploring',
  'validating',
  'ready',
  'parked',
  'dropped',
]

export const STATUS_LABELS: Record<IdeaStatus, string> = {
  inbox: 'Inbox',
  exploring: 'Exploring',
  validating: 'Validating',
  ready: 'Ready',
  converted: 'Converted',
  parked: 'Parked',
  dropped: 'Dropped',
}

export const SOURCE_LABELS: Record<IdeaSource, string> = {
  manual: 'My idea',
  pain_point_report: 'Pain-point report',
  customer: 'Customer',
  other: 'Other',
}

export const KIND_LABELS: Record<EntryKind, string> = {
  note: 'Note',
  image: 'Image',
  link: 'Link',
  sketch: 'Sketch',
  measurement: 'Measurement',
  decision: 'Decision',
  generation: 'Generated',
}

export const SCORE_LABELS: Record<ScoreName, string> = {
  frequency: 'Frequency',
  frustration: 'Frustration',
  printability: 'Printability',
  gap: 'Gap',
  willingness_to_pay: 'Willingness to pay',
}

export const SCORE_NAMES = Object.keys(SCORE_LABELS) as ScoreName[]

/** "18/25", "Report score 20/25" or "Not scored" — the backend computes the figure. */
export function scoreText(idea: Pick<IdeaSummary, 'score' | 'score_source'>): string {
  if (idea.score === null || idea.score === undefined) return 'Not scored'
  if (idea.score_source === 'report') return `Report score ${idea.score}/25`
  return `${idea.score}/25`
}

/** Image types an idea accepts, as the product images do (FR-014, FR-020). */
export const ACCEPTED_IMAGES = ['image/jpeg', 'image/png', 'image/webp']

/** Entries by iteration, latest first, keeping the order the backend gave within one. */
export function groupByIteration(entries: IdeaEntry[]): [number, IdeaEntry[]][] {
  const groups = new Map<number, IdeaEntry[]>()
  for (const entry of entries) {
    const group = groups.get(entry.iteration) ?? []
    group.push(entry)
    groups.set(entry.iteration, group)
  }
  return [...groups.entries()].sort(([a], [b]) => b - a)
}

export type PreviewState = 'create' | 'skip' | 'refused'

export interface PreviewRow {
  item: ImportItem
  state: PreviewState
  reason: string | null
}

/**
 * Each parsed problem beside what the dry run will do with it (FR-031, US4/AC1).
 *
 * The dry run reports refusals by index and skips by source link. A link
 * already in the shop skips every occurrence; a link repeated in the report
 * skips every occurrence after the first. Either way the skipped ones are the
 * last occurrences, so the count per link is enough to place them.
 */
export function previewRows(items: ImportItem[], result: ImportResult): PreviewRow[] {
  const refused = new Map(result.refused.map((r) => [r.index, r.reason]))
  const skipsLeft = new Map<string, number>()
  for (const s of result.skipped) {
    if (s.source_url) skipsLeft.set(s.source_url, (skipsLeft.get(s.source_url) ?? 0) + 1)
  }
  const rows: PreviewRow[] = items.map((item, index) => ({
    item,
    state: refused.has(index) ? 'refused' : 'create',
    reason: refused.get(index) ?? null,
  }))
  for (let index = rows.length - 1; index >= 0; index--) {
    const url = rows[index].item.source_url
    const left = url ? (skipsLeft.get(url) ?? 0) : 0
    if (rows[index].state === 'create' && url && left > 0) {
      rows[index].state = 'skip'
      skipsLeft.set(url, left - 1)
    }
  }
  return rows
}
