/** The board: a column per status, a page each, more on demand (spec 007, FR-008, FR-010). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor, within } from '@/test/test-utils'
import type { IdeaListParams } from '@/types/idea'

import { COLUMN_PAGE, IdeaBoard } from './IdeaBoard'
import { aSummary } from './ideaTestData'

const api = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn(), getImageBlob: vi.fn() }))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

beforeEach(() => {
  api.list.mockReset()
  api.update.mockReset()
  api.list.mockImplementation(async (params: IdeaListParams) => {
    if (params.status?.[0] === 'inbox') {
      const limit = params.limit ?? COLUMN_PAGE
      const items = Array.from({ length: Math.min(limit, 30) }, (_, i) =>
        aSummary({ id: `idea-${i}`, title: `Idea ${i}` })
      )
      return { items, total: 30, skip: 0, limit }
    }
    return { items: [], total: 0, skip: 0, limit: params.limit }
  })
})

describe('IdeaBoard', () => {
  it('asks each column for one page of its own status, never every idea', async () => {
    render(<IdeaBoard canWrite />)
    const inbox = await screen.findByRole('region', { name: 'Inbox' })
    expect(await within(inbox).findByLabelText('30 ideas')).toBeInTheDocument()
    expect(within(inbox).getAllByRole('article')).toHaveLength(COLUMN_PAGE)
    for (const call of api.list.mock.calls) {
      expect(call[0].status).toHaveLength(1)
      expect(call[0].limit).toBe(COLUMN_PAGE)
    }
    expect(screen.getByRole('region', { name: 'Converted' })).toBeInTheDocument()
  })

  it('loads more on demand', async () => {
    render(<IdeaBoard canWrite />)
    const inbox = await screen.findByRole('region', { name: 'Inbox' })
    await within(inbox).findAllByRole('article')
    await userEvent.click(within(inbox).getByRole('button', { name: 'Load more' }))
    await waitFor(() => expect(within(inbox).getAllByRole('article')).toHaveLength(30))
  })

  it('moves a card with the status menu', async () => {
    api.update.mockResolvedValue(aSummary())
    render(<IdeaBoard canWrite />)
    await userEvent.selectOptions(await screen.findByLabelText('Move Idea 0'), 'exploring')
    expect(api.update).toHaveBeenCalledWith('idea-0', { status: 'exploring' })
  })

  it('offers to create or import when there is no idea', async () => {
    api.list.mockResolvedValue({ items: [], total: 0, skip: 0, limit: COLUMN_PAGE })
    const onNewIdea = vi.fn()
    const onImport = vi.fn()
    render(<IdeaBoard canWrite onNewIdea={onNewIdea} onImport={onImport} />)
    await userEvent.click(await screen.findByRole('button', { name: 'New idea' }))
    await userEvent.click(screen.getByRole('button', { name: 'Import report' }))
    expect(onNewIdea).toHaveBeenCalled()
    expect(onImport).toHaveBeenCalled()
  })
})
