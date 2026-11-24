/** The timeline groups entries by iteration, latest first (spec 007, FR-016, FR-017, FR-018). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'

import { IdeaTimeline } from './IdeaTimeline'
import { IdeaGallery } from './IdeaGallery'
import { anEntry, anImageEntry } from './ideaTestData'

const api = vi.hoisted(() => ({
  listEntries: vi.fn(),
  updateEntry: vi.fn(),
  update: vi.fn(),
  getImageBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

beforeEach(() => {
  api.listEntries.mockReset()
  api.update.mockReset()
  api.listEntries.mockResolvedValue({
    items: [
      anEntry({ id: 'n2', iteration: 2, body: 'Second round' }),
      anImageEntry({ iteration: 1 }),
      anEntry({ id: 'n1', iteration: 1, body: 'First round' }),
    ],
    current_iteration: 2,
  })
})

describe('IdeaTimeline', () => {
  it('shows the latest iteration first', async () => {
    render(<IdeaTimeline ideaId="idea-1" coverEntryId={null} canWrite />)
    await screen.findByText('Second round')
    const headings = screen.getAllByRole('heading').map((h) => h.textContent)
    expect(headings).toEqual(['Iteration 2', 'Iteration 1'])
  })

  it('asks for archived entries only when shown', async () => {
    render(<IdeaTimeline ideaId="idea-1" coverEntryId={null} canWrite />)
    await screen.findByText('Second round')
    expect(api.listEntries).toHaveBeenLastCalledWith('idea-1', false)
    await userEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(api.listEntries).toHaveBeenLastCalledWith('idea-1', true))
  })

  it('sets the cover on the idea', async () => {
    api.update.mockResolvedValue({})
    render(<IdeaTimeline ideaId="idea-1" coverEntryId={null} canWrite />)
    await userEvent.click(await screen.findByRole('button', { name: 'Set as cover' }))
    expect(api.update).toHaveBeenCalledWith('idea-1', { cover_entry_id: 'entry-img' })
  })

  it('says when there is nothing yet', async () => {
    api.listEntries.mockResolvedValue({ items: [], current_iteration: 1 })
    render(<IdeaTimeline ideaId="idea-1" coverEntryId={null} canWrite />)
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument()
  })
})

describe('IdeaGallery', () => {
  it('shows every image with its iteration and nothing else', async () => {
    api.listEntries.mockResolvedValue({
      items: [
        anImageEntry({ id: 'i2', iteration: 2, original_filename: 'b.png', kind: 'sketch' }),
        anImageEntry({ id: 'i1', iteration: 1, original_filename: 'a.png' }),
        anEntry(),
      ],
      current_iteration: 2,
    })
    render(<IdeaGallery ideaId="idea-1" />)
    expect(await screen.findByRole('button', { name: 'Open b.png' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open a.png' })).toBeInTheDocument()
    expect(screen.getByText('Iteration 2')).toBeInTheDocument()
    expect(screen.getByText('Sketch')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('says when there is no image', async () => {
    api.listEntries.mockResolvedValue({ items: [anEntry()], current_iteration: 1 })
    render(<IdeaGallery ideaId="idea-1" />)
    expect(await screen.findByText('No image yet.')).toBeInTheDocument()
  })
})
