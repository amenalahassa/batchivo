/** One timeline entry and its actions (spec 007, FR-013, FR-016, FR-018, T032). */
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen } from '@/test/test-utils'

import { IdeaEntryItem } from './IdeaEntryItem'
import { anEntry, anImageEntry } from './ideaTestData'

vi.mock('@/lib/api/ideas', () => ({ ideasApi: { getImageBlob: vi.fn(() => new Promise(() => {})) } }))

function renderItem(props: Partial<Parameters<typeof IdeaEntryItem>[0]> = {}) {
  const onUpdate = vi.fn()
  const onSetCover = vi.fn()
  render(
    <ul>
      <IdeaEntryItem
        entry={anEntry()}
        canWrite
        onUpdate={onUpdate}
        onSetCover={onSetCover}
        {...props}
      />
    </ul>
  )
  return { onUpdate, onSetCover }
}

describe('IdeaEntryItem', () => {
  it('shows the markdown text, the author and that it was edited', () => {
    renderItem({ entry: anEntry({ edited_at: '2026-11-21T10:00:00Z' }) })
    expect(screen.getByText('note').tagName).toBe('STRONG')
    expect(screen.getByText(/Ada/)).toBeInTheDocument()
    expect(screen.getByText('(edited)')).toBeInTheDocument()
  })

  it('pins and archives', async () => {
    const { onUpdate } = renderItem()
    await userEvent.click(screen.getByRole('button', { name: 'Pin entry' }))
    await userEvent.click(screen.getByRole('button', { name: 'Archive entry' }))
    expect(onUpdate).toHaveBeenCalledWith('entry-1', { pinned: true })
    expect(onUpdate).toHaveBeenCalledWith('entry-1', { archived: true })
  })

  it('edits the text inline', async () => {
    const { onUpdate } = renderItem()
    await userEvent.click(screen.getByRole('button', { name: 'Edit entry' }))
    const box = screen.getByLabelText('Entry text')
    await userEvent.clear(box)
    await userEvent.type(box, 'Changed')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onUpdate).toHaveBeenCalledWith('entry-1', { body: 'Changed' })
  })

  it('sets an image as the cover, and clears it', async () => {
    const { onSetCover } = renderItem({ entry: anImageEntry() })
    await userEvent.click(screen.getByRole('button', { name: 'Set as cover' }))
    expect(onSetCover).toHaveBeenCalledWith('entry-img')
  })

  it('clears the cover from the cover entry', async () => {
    const { onSetCover } = renderItem({ entry: anImageEntry(), isCover: true })
    expect(screen.getByText('Cover')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear cover' }))
    expect(onSetCover).toHaveBeenCalledWith(null)
  })

  it('opens a link in a new tab', () => {
    renderItem({ entry: anEntry({ kind: 'link', link_url: 'https://example.com', body: null }) })
    expect(screen.getByRole('link', { name: 'https://example.com' })).toHaveAttribute(
      'target',
      '_blank'
    )
  })

  it('gives a viewer no action', () => {
    renderItem({ canWrite: false, entry: anImageEntry() })
    expect(screen.queryByRole('button', { name: 'Pin entry' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Set as cover' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open clip.png' })).toBeInTheDocument()
  })

  it('restores an archived entry', async () => {
    const { onUpdate } = renderItem({ entry: anEntry({ archived: true }) })
    await userEvent.click(screen.getByRole('button', { name: 'Restore entry' }))
    expect(onUpdate).toHaveBeenCalledWith('entry-1', { archived: false })
  })
})
