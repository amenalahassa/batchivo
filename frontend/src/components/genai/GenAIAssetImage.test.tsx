/** Generation files are loaded with the session, never by a public URL (spec 008). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen } from '@/test/test-utils'

import { AdoptConfirmDialog } from './AdoptConfirmDialog'
import { AIBadge } from './AIBadge'
import { GenAIAssetImage } from './GenAIAssetImage'
import { JobStatusBadge } from './JobStatusBadge'
import { MeshPreview } from './MeshPreview'

const api = vi.hoisted(() => ({ getBlob: vi.fn() }))
vi.mock('@/lib/api/genai', () => ({ genaiApi: api }))
vi.mock('@/components/viewer/GlbView', () => ({
  default: ({ blob }: { blob: Blob }) => <div>3D view of {blob.size} bytes</div>,
}))

beforeEach(() => {
  api.getBlob.mockReset()
  URL.createObjectURL = vi.fn(() => 'blob:mock')
  URL.revokeObjectURL = vi.fn()
})

describe('GenAIAssetImage', () => {
  it('fetches the file with the session and shows it', async () => {
    api.getBlob.mockResolvedValue(new Blob(['png'], { type: 'image/png' }))
    render(<GenAIAssetImage path="/api/v1/genai/assets/a/file" alt="Result 1" />)
    expect(await screen.findByRole('img', { name: 'Result 1' })).toHaveAttribute('src', 'blob:mock')
    expect(api.getBlob).toHaveBeenCalledWith('/api/v1/genai/assets/a/file')
  })

  it('says when the file is missing', async () => {
    api.getBlob.mockRejectedValue(new Error('404'))
    render(<GenAIAssetImage path="/api/v1/genai/assets/a/file" alt="Result 1" />)
    expect(await screen.findByRole('img', { name: 'Result 1 (image missing)' })).toBeInTheDocument()
  })
})

describe('MeshPreview', () => {
  it('shows the draft in the lazy viewer with a download', async () => {
    api.getBlob.mockResolvedValue(new Blob(['glTF'], { type: 'model/gltf-binary' }))
    render(<MeshPreview path="/api/v1/genai/assets/m/file" filename="draft.glb" />)
    expect(await screen.findByText('3D view of 4 bytes')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Download' })
    expect(link).toHaveAttribute('download', 'draft.glb')
    expect(link).toHaveAttribute('href', 'blob:mock')
  })

  it('says when the draft cannot be loaded', async () => {
    api.getBlob.mockRejectedValue(new Error('404'))
    render(<MeshPreview path="/api/v1/genai/assets/m/file" />)
    expect(await screen.findByText('The 3D draft could not be loaded')).toBeInTheDocument()
  })
})

describe('badges and confirmation', () => {
  it('marks AI pictures and job states', () => {
    render(
      <>
        <AIBadge />
        <JobStatusBadge status="running" />
      </>
    )
    expect(screen.getByLabelText('AI: made with generative AI')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Generating…')
  })

  it('warns that listings must show the real item', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(<AdoptConfirmDialog open onConfirm={onConfirm} onCancel={onCancel} />)
    expect(screen.getByText('Listings must show the real item')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add anyway' }))
    expect(onConfirm).toHaveBeenCalled()
  })
})
