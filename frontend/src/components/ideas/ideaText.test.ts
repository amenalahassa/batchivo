// @vitest-environment node
/** Words and grouping for ideas (spec 007, FR-004, FR-004a, FR-017). */
import { describe, expect, it } from 'vitest'

import { anEntry } from './ideaTestData'
import {
  BOARD_STATUSES,
  WRITABLE_STATUSES,
  groupByIteration,
  previewRows,
  scoreText,
} from './ideaText'

describe('scoreText', () => {
  it('shows the total out of 25 when the five scores are set', () => {
    expect(scoreText({ score: 18, score_source: 'scores' })).toBe('18/25')
  })

  it('names a report score as one', () => {
    expect(scoreText({ score: 20, score_source: 'report' })).toBe('Report score 20/25')
  })

  it('shows an unscored idea as not scored, never as zero', () => {
    expect(scoreText({ score: null, score_source: null })).toBe('Not scored')
  })
})

describe('statuses', () => {
  it('never lets an operator pick converted', () => {
    expect(WRITABLE_STATUSES).not.toContain('converted')
    expect(BOARD_STATUSES).toContain('converted')
  })
})

describe('groupByIteration', () => {
  it('puts the latest iteration first and keeps the order within one', () => {
    const groups = groupByIteration([
      anEntry({ id: 'a', iteration: 2 }),
      anEntry({ id: 'b', iteration: 2 }),
      anEntry({ id: 'c', iteration: 1 }),
    ])
    expect(groups.map(([n]) => n)).toEqual([2, 1])
    expect(groups[0][1].map((e) => e.id)).toEqual(['a', 'b'])
  })

  it('returns nothing for no entry', () => {
    expect(groupByIteration([])).toEqual([])
  })
})

describe('previewRows', () => {
  const item = (title: string, source_url?: string) => ({ title, source_url })

  it('places refusals by index and skips by link', () => {
    const rows = previewRows([item('a', 'u1'), item(''), item('c', 'u3')], {
      created: [{ id: null, title: 'c' }],
      skipped: [{ title: 'a', source_url: 'u1', existing_idea_id: 'x' }],
      refused: [{ index: 1, title: null, reason: 'Title is required' }],
    })
    expect(rows.map((r) => [r.state, r.reason])).toEqual([
      ['skip', null],
      ['refused', 'Title is required'],
      ['create', null],
    ])
  })

  it('creates the first of a link repeated in the report and skips the rest', () => {
    const rows = previewRows([item('a', 'u'), item('b', 'u')], {
      created: [{ id: null, title: 'a' }],
      skipped: [{ title: 'b', source_url: 'u', existing_idea_id: null }],
      refused: [],
    })
    expect(rows.map((r) => r.state)).toEqual(['create', 'skip'])
  })

  it('skips every occurrence of a link already in the shop', () => {
    const rows = previewRows([item('a', 'u'), item('b', 'u')], {
      created: [],
      skipped: [
        { title: 'a', source_url: 'u', existing_idea_id: 'x' },
        { title: 'b', source_url: 'u', existing_idea_id: 'x' },
      ],
      refused: [],
    })
    expect(rows.map((r) => r.state)).toEqual(['skip', 'skip'])
  })
})
