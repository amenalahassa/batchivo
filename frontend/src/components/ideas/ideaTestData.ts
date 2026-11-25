/**
 * Ideas and entries for the ideas component tests (spec 007).
 */
import type { IdeaDetail, IdeaEntry, IdeaScores, IdeaSummary } from '@/types/idea'

export const NO_SCORES: IdeaScores = {
  frequency: null,
  frustration: null,
  printability: null,
  gap: null,
  willingness_to_pay: null,
}

export function anIdea(overrides: Partial<IdeaDetail> = {}): IdeaDetail {
  return {
    id: 'idea-1',
    title: 'Sun visor clip',
    summary: 'Holds **cards** on the visor',
    status: 'inbox',
    source: 'manual',
    source_url: null,
    tags: ['car'],
    scores: NO_SCORES,
    report_score: null,
    score: null,
    score_source: null,
    cover_thumbnail_path: null,
    cover_image_path: null,
    cover_entry_id: null,
    current_iteration: 1,
    archived: false,
    model: { id: null, name: null, sku: null, state: 'none' },
    product: { id: null, name: null, sku: null, state: 'none' },
    created_by: { id: 'user-1', name: 'Ada' },
    created_at: '2026-11-20T10:00:00Z',
    updated_at: '2026-11-21T10:00:00Z',
    ...overrides,
  }
}

export function aSummary(overrides: Partial<IdeaSummary> = {}): IdeaSummary {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { summary, cover_entry_id, cover_image_path, created_by, ...rest } = anIdea()
  return { ...rest, ...overrides }
}

export function anEntry(overrides: Partial<IdeaEntry> = {}): IdeaEntry {
  return {
    id: 'entry-1',
    idea_id: 'idea-1',
    kind: 'note',
    iteration: 1,
    body: 'First **note**',
    link_url: null,
    pinned: false,
    archived: false,
    image_path: null,
    thumbnail_path: null,
    content_type: null,
    original_filename: null,
    file_size: null,
    generation_job_id: null,
    author: { id: 'user-1', name: 'Ada' },
    created_at: '2026-11-20T10:00:00Z',
    edited_at: null,
    ...overrides,
  }
}

export function anImageEntry(overrides: Partial<IdeaEntry> = {}): IdeaEntry {
  return anEntry({
    id: 'entry-img',
    kind: 'image',
    body: null,
    image_path: '/api/v1/ideas/idea-1/entries/entry-img/image?variant=full',
    thumbnail_path: '/api/v1/ideas/idea-1/entries/entry-img/image?variant=thumb',
    content_type: 'image/png',
    original_filename: 'clip.png',
    file_size: 1200,
    ...overrides,
  })
}
