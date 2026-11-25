/** One timeline entry and its actions (spec 007, FR-013, FR-016, FR-018, T032). */
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen } from '@/test/test-utils'
import { aJob, anAsset, capabilities } from '@/components/genai/genaiTestData'

import { IdeaEntryItem } from './IdeaEntryItem'
import { anEntry, anImageEntry } from './ideaTestData'

vi.mock('@/lib/api/ideas', () => ({
  ideasApi: { getImageBlob: vi.fn(() => new Promise(() => {})) },
}))

const genai = vi.hoisted(() => ({
  getJob: vi.fn(),
  getBlob: vi.fn(),
  capabilities: vi.fn(),
  estimate: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: genai }))
const genaiRoles = vi.hoisted(() => ({
  value: { canGenerate: false, canManageSettings: false },
}))
vi.mock('@/components/genai/useGenAIRoles', () => ({
  useGenAIRoles: () => genaiRoles.value,
}))
vi.mock('@/components/viewer/GlbView', () => ({
  default: () => <div data-testid="glb-view">3D view</div>,
}))

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
    renderItem({
      entry: anEntry({
        kind: 'link',
        link_url: 'https://example.com',
        body: null,
      }),
    })
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

  // ============================================
  // Generative AI (spec 008, T039)
  // ============================================

  it('offers the AI actions on an image entry to a member', async () => {
    genaiRoles.value = { canGenerate: true, canManageSettings: false }
    genai.capabilities.mockResolvedValue(capabilities())
    renderItem({ entry: anImageEntry() })
    const group = screen.getByRole('group', { name: 'AI actions' })
    expect(group).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit with AI' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Draft 3D shape' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Variations' }))
    expect(await screen.findByDisplayValue(/Make a variation of this design/)).toBeInTheDocument()
    genaiRoles.value = { canGenerate: false, canManageSettings: false }
  })

  it('offers the AI actions on a generated picture to a member', () => {
    genaiRoles.value = { canGenerate: true, canManageSettings: false }
    genai.getJob.mockResolvedValue(aJob({ id: 'job-9', status: 'succeeded' }))
    genai.capabilities.mockResolvedValue(capabilities())
    renderItem({
      entry: anImageEntry({
        id: 'entry-gen',
        kind: 'generation',
        generation_job_id: 'job-9',
      }),
    })
    expect(screen.getByRole('group', { name: 'AI actions' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit with AI' })).toBeInTheDocument()
    genaiRoles.value = { canGenerate: false, canManageSettings: false }
  })

  it('hides the AI actions from a viewer', () => {
    genaiRoles.value = { canGenerate: false, canManageSettings: false }
    renderItem({ entry: anImageEntry({ kind: 'sketch' }) })
    expect(screen.queryByRole('group', { name: 'AI actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit with AI' })).not.toBeInTheDocument()
  })

  it('shows a generated picture with the AI badge and how it was made', async () => {
    genai.getJob.mockResolvedValue(aJob({ id: 'job-9', status: 'succeeded' }))
    renderItem({
      entry: anImageEntry({
        id: 'entry-gen',
        kind: 'generation',
        generation_job_id: 'job-9',
      }),
    })
    expect(screen.getByLabelText('AI: made with generative AI')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open clip.png' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'AI actions' })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'How it was made' }))
    expect(await screen.findByText('black-forest-labs/flux-schnell')).toBeInTheDocument()
  })

  it('shows a generated 3D draft through its job output', async () => {
    const mesh = anAsset({
      id: 'mesh-1',
      kind: 'mesh',
      content_type: 'model/gltf-binary',
      original_filename: 'draft.glb',
      thumbnail_path: null,
      adoptions: [
        {
          owner_type: 'idea',
          owner_id: 'idea-1',
          idea_entry_id: 'entry-mesh',
          product_image_id: null,
          model_file_id: null,
          warning_confirmed: false,
          created_at: '2026-11-24T10:00:00Z',
        },
      ],
    })
    genai.getJob.mockResolvedValue(
      aJob({
        id: 'job-3d',
        capability: 'image_to_3d',
        status: 'succeeded',
        outputs: [mesh],
      })
    )
    genai.getBlob.mockResolvedValue(new Blob(['glb']))
    URL.createObjectURL = vi.fn(() => 'blob:mesh')
    URL.revokeObjectURL = vi.fn()
    renderItem({
      entry: anEntry({
        id: 'entry-mesh',
        kind: 'generation',
        body: null,
        generation_job_id: 'job-3d',
      }),
    })
    expect(await screen.findByTestId('glb-view')).toBeInTheDocument()
    expect(genai.getJob).toHaveBeenCalledWith('job-3d')
    expect(genai.getBlob).toHaveBeenCalledWith('/api/v1/genai/assets/mesh-1/file')
  })
})
