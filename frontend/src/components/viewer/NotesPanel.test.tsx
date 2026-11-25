/**
 * Notes listed beside the viewer (spec 004, T054; FR-028, FR-029, FR-032).
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NotesPanel } from './NotesPanel'
import type { FileNote } from '@/types/model-file-version'

const note = (over: Partial<FileNote>): FileNote => ({
  id: 'n',
  number: 1,
  model_file_id: 'f2',
  version_id: 'v2',
  position: [1, 2, 3],
  normal: [0, 0, 1],
  layer: null,
  text: 'overhang sags',
  status: 'open',
  resolved_in_version_id: null,
  carried_to_version_id: null,
  carried_from_note_id: null,
  author: { id: 'u', name: 'Konrad' },
  created_at: '2026-11-01T10:00:00Z',
  archived_at: null,
  ghost: false,
  ...over,
})

const NOTES = [
  note({ id: 'a', number: 1, text: 'seam visible' }),
  note({ id: 'b', number: 2, text: 'fixed corner', status: 'resolved', resolved_in_version_id: 'v2' }),
  note({ id: 'g', number: 3, text: 'thin wall', version_id: 'v1', ghost: true }),
]

function renderPanel(canWrite = true) {
  const handlers = {
    onResolve: vi.fn(),
    onCarryForward: vi.fn(),
    onReopen: vi.fn(),
    onIncludeArchivedChange: vi.fn(),
  }
  render(<NotesPanel notes={NOTES} canWrite={canWrite} includeArchived={false} {...handlers} />)
  return handlers
}

describe('NotesPanel', () => {
  it('lists every note with its author', () => {
    renderPanel()
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    expect(screen.getAllByText(/Konrad/)).toHaveLength(3)
    expect(screen.getByText('Earlier version')).toBeInTheDocument()
  })

  it('filters by status', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: 'Resolved' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(screen.getByText('fixed corner')).toBeInTheDocument()
  })

  it('resolves or carries forward a ghost note', async () => {
    const handlers = renderPanel()
    const ghost = screen.getByText('thin wall').closest('li') as HTMLElement
    await userEvent.click(within(ghost).getByRole('button', { name: 'Resolved in this version' }))
    expect(handlers.onResolve).toHaveBeenCalledWith(expect.objectContaining({ id: 'g' }))
    await userEvent.click(within(ghost).getByRole('button', { name: 'Carry forward' }))
    expect(handlers.onCarryForward).toHaveBeenCalledWith(expect.objectContaining({ id: 'g' }))
  })

  it('reopens a resolved note', async () => {
    const handlers = renderPanel()
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(handlers.onReopen).toHaveBeenCalledWith(expect.objectContaining({ id: 'b' }))
  })

  it('toggles archived notes', async () => {
    const handlers = renderPanel()
    await userEvent.click(screen.getByRole('switch', { name: 'Show archived notes' }))
    expect(handlers.onIncludeArchivedChange).toHaveBeenCalledWith(true)
  })

  it('shows a viewer no write action', () => {
    renderPanel(false)
    for (const name of ['Resolve', 'Resolved in this version', 'Carry forward', 'Reopen']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(screen.getByText('thin wall')).toBeInTheDocument()
  })
})
