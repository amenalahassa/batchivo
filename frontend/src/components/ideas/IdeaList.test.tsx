/** The list: search, filters, sort, pages and restore (spec 007, FR-006, FR-009). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'

import { IdeaList, LIST_PAGE } from './IdeaList'
import { aSummary } from './ideaTestData'

const api = vi.hoisted(() => ({ list: vi.fn(), tags: vi.fn(), update: vi.fn() }))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

beforeEach(() => {
  api.list.mockReset()
  api.tags.mockResolvedValue(['car', 'kitchen'])
  api.update.mockReset()
  api.list.mockResolvedValue({
    items: [
      aSummary({ id: 'a', title: 'Visor clip', score: 18, score_source: 'scores' }),
      aSummary({ id: 'b', title: 'Old idea', archived: true }),
    ],
    total: 2,
    skip: 0,
    limit: LIST_PAGE,
  })
})

describe('IdeaList', () => {
  it('lists ideas with their score, last updated first', async () => {
    render(<IdeaList canWrite />)
    expect(await screen.findByRole('link', { name: 'Visor clip' })).toBeInTheDocument()
    expect(screen.getByText('18/25')).toBeInTheDocument()
    expect(api.list).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'updated', archived: 'false', skip: 0, limit: LIST_PAGE })
    )
  })

  it('searches after the operator stops typing', async () => {
    render(<IdeaList canWrite />)
    await screen.findByRole('link', { name: 'Visor clip' })
    await userEvent.type(screen.getByLabelText('Search ideas'), 'visor')
    await waitFor(() =>
      expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'visor' }))
    )
    const searches = api.list.mock.calls.filter((c) => c[0].search)
    expect(searches).toHaveLength(1)
  })

  it('filters by tag and sorts by score', async () => {
    render(<IdeaList canWrite />)
    await screen.findByRole('option', { name: 'kitchen' })
    await userEvent.selectOptions(screen.getByLabelText('Tag'), 'kitchen')
    await userEvent.selectOptions(screen.getByLabelText('Sort'), 'score')
    await waitFor(() =>
      expect(api.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ tag: ['kitchen'], sort: 'score' })
      )
    )
  })

  it('restores an archived idea', async () => {
    api.update.mockResolvedValue(aSummary())
    render(<IdeaList canWrite />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restore' }))
    expect(api.update).toHaveBeenCalledWith('b', { archived: false })
  })

  it('gives a viewer no restore', async () => {
    render(<IdeaList canWrite={false} />)
    await screen.findByRole('link', { name: 'Old idea' })
    expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()
  })

  it('pages through many ideas', async () => {
    api.list.mockResolvedValue({ items: [aSummary()], total: 60, skip: 0, limit: LIST_PAGE })
    render(<IdeaList canWrite />)
    await userEvent.click(await screen.findByRole('button', { name: 'Next' }))
    await waitFor(() =>
      expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ skip: LIST_PAGE }))
    )
  })
})
