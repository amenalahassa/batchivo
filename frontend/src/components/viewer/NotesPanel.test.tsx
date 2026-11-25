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
  source: 'person',
  rule_id: null,
  severity: 'info',
  measured_value: null,
  expected_value: null,
  value_unit: null,
  dismissal_reason: null,
  dismissed_at: null,
  dismissed_by: null,
  ...over,
})

const NOTES = [
  note({ id: 'a', number: 1, text: 'seam visible' }),
  note({ id: 'b', number: 2, text: 'fixed corner', status: 'resolved', resolved_in_version_id: 'v2' }),
  note({ id: 'g', number: 3, text: 'thin wall', version_id: 'v1', ghost: true }),
]

function renderPanel(canWrite = true, notes = NOTES) {
  const handlers = {
    onResolve: vi.fn(),
    onCarryForward: vi.fn(),
    onReopen: vi.fn(),
    onDismiss: vi.fn(),
    onIncludeArchivedChange: vi.fn(),
  }
  render(<NotesPanel notes={notes} canWrite={canWrite} includeArchived={false} {...handlers} />)
  return handlers
}

const FINDING = note({
  id: 'p',
  number: 4,
  text: 'Paroi trop fine',
  source: 'preflight',
  severity: 'failure',
  rule_id: 'dfam.wall.extrusion-multiple',
  measured_value: '0.6',
  expected_value: '0.9',
  value_unit: 'mm',
})

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

  it('shows a plain note exactly as before, with no type filters', () => {
    renderPanel()
    expect(screen.queryByRole('group', { name: 'Filter by source' })).not.toBeInTheDocument()
    expect(screen.queryByText('Info')).not.toBeInTheDocument()
  })

  it('shows a finding with its severity, rule and measure', () => {
    renderPanel(true, [...NOTES, FINDING])
    const item = screen.getByText('Paroi trop fine').closest('li') as HTMLElement
    expect(within(item).getByText('Failure')).toBeInTheDocument()
    expect(within(item).getByText('Preflight')).toBeInTheDocument()
    expect(within(item).getByText('dfam.wall.extrusion-multiple')).toBeInTheDocument()
    expect(item).toHaveTextContent('0.6 mm (expected 0.9 mm)')
  })

  it('filters by source and by severity', async () => {
    renderPanel(true, [...NOTES, FINDING])
    await userEvent.click(
      within(screen.getByRole('group', { name: 'Filter by source' })).getByRole('button', { name: 'Preflight' })
    )
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Any source' }))
    await userEvent.click(screen.getByRole('button', { name: 'Warnings' }))
    expect(screen.getByText('No notes match.')).toBeInTheDocument()
  })

  it('dismisses an open note only with a reason', async () => {
    const handlers = renderPanel(true, [FINDING])
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    const save = screen.getByRole('button', { name: 'Dismiss note' })
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Why is this note dismissed?'), '   ')
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Why is this note dismissed?'), 'Cosmetic face')
    await userEvent.click(save)
    expect(handlers.onDismiss).toHaveBeenCalledWith(expect.objectContaining({ id: 'p' }), 'Cosmetic face')
  })

  it('shows why a note was dismissed and reopens it', async () => {
    const dismissed = note({
      ...FINDING,
      status: 'dismissed',
      dismissal_reason: 'Accepted for a prototype',
      dismissed_by: { id: 'u', name: 'Konrad' },
    })
    const handlers = renderPanel(true, [dismissed])
    expect(screen.getByText(/Accepted for a prototype/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dismiss' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(handlers.onReopen).toHaveBeenCalledWith(expect.objectContaining({ id: 'p' }))
  })
})
