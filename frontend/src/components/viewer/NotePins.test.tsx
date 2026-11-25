/**
 * A pin's badge and tooltip, outside the canvas (spec 004, T054; FR-026, FR-029).
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DraftNote, PinBadge } from './NotePins'
import type { FileNote } from '@/types/model-file-version'

const note = (over: Partial<FileNote> = {}): FileNote => ({
  id: 'n1',
  number: 4,
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

const actions = () => ({ onResolve: vi.fn(), onCarryForward: vi.fn(), onMove: vi.fn() })

describe('PinBadge', () => {
  it('shows its number, and the note on hover', async () => {
    render(<PinBadge note={note()} canWrite {...actions()} />)
    const pin = screen.getByRole('button', { name: 'Note 4' })
    expect(pin).toHaveTextContent('4')
    await userEvent.hover(pin)
    expect(screen.getByRole('tooltip')).toHaveTextContent('overhang sags')
  })

  it('offers "Resolved in this version" and "Carry forward" on a ghost pin', async () => {
    const a = actions()
    render(<PinBadge note={note({ ghost: true })} canWrite {...a} />)
    await userEvent.click(screen.getByRole('button', { name: 'Note 4 from an earlier version' }))
    await userEvent.click(screen.getByRole('button', { name: 'Resolved in this version' }))
    expect(a.onResolve).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Carry forward' }))
    expect(a.onCarryForward).toHaveBeenCalled()
  })

  it('lets an open note of this file be moved', async () => {
    const a = actions()
    render(<PinBadge note={note()} canWrite {...a} />)
    await userEvent.click(screen.getByRole('button', { name: 'Note 4' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move' }))
    expect(a.onMove).toHaveBeenCalled()
  })

  it('shows a viewer the note but no action', async () => {
    render(<PinBadge note={note({ ghost: true })} canWrite={false} {...actions()} />)
    await userEvent.click(screen.getByRole('button', { name: /Note 4/ }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('overhang sags')
    expect(screen.queryByRole('button', { name: 'Carry forward' })).not.toBeInTheDocument()
  })
})

describe('DraftNote', () => {
  it('saves the typed text', async () => {
    const onSave = vi.fn()
    render(<DraftNote onSave={onSave} onCancel={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Pin note' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Note text'), 'thin wall')
    await userEvent.click(screen.getByRole('button', { name: 'Pin note' }))
    expect(onSave).toHaveBeenCalledWith('thin wall')
  })
})
