/** Idea images load with the session, never by a public URL (spec 007, Q1, FR-022). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { render, screen } from '@/test/test-utils'

import { AuthImage } from './AuthImage'
import { Markdown } from './Markdown'

const api = vi.hoisted(() => ({ getImageBlob: vi.fn() }))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

const PATH = '/api/v1/ideas/i/entries/e/image?variant=thumb'

beforeEach(() => {
  api.getImageBlob.mockReset()
  URL.createObjectURL = vi.fn(() => 'blob:idea-image')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.restoreAllMocks())

describe('AuthImage', () => {
  it('fetches the image with the session and shows it through an object URL', async () => {
    api.getImageBlob.mockResolvedValue(new Blob(['x'], { type: 'image/png' }))
    render(<AuthImage path={PATH} alt="Clip" />)
    const img = await screen.findByRole('img', { name: 'Clip' })
    expect(img).toHaveAttribute('src', 'blob:idea-image')
    expect(api.getImageBlob).toHaveBeenCalledWith(PATH)
  })

  it('shows a placeholder when the image is missing', async () => {
    api.getImageBlob.mockRejectedValue(new Error('404'))
    render(<AuthImage path={PATH} alt="Clip" />)
    expect(await screen.findByRole('img', { name: 'Clip (image missing)' })).toBeInTheDocument()
  })

  it('renders nothing without a path', () => {
    const { container } = render(<AuthImage path={null} alt="Clip" />)
    expect(container).toBeEmptyDOMElement()
    expect(api.getImageBlob).not.toHaveBeenCalled()
  })

  it('revokes the object URL when it goes away', async () => {
    api.getImageBlob.mockResolvedValue(new Blob(['x'], { type: 'image/png' }))
    const { unmount } = render(<AuthImage path={PATH} alt="Clip" />)
    await screen.findByRole('img', { name: 'Clip' })
    unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:idea-image')
  })
})

describe('Markdown', () => {
  it('renders markdown and opens links in a new tab without access to the page', () => {
    render(<Markdown>{'**bold** and [a link](https://example.com)'}</Markdown>)
    expect(screen.getByText('bold').tagName).toBe('STRONG')
    const link = screen.getByRole('link', { name: 'a link' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('never renders raw HTML', () => {
    const { container } = render(<Markdown>{'<script>alert(1)</script><b>x</b>'}</Markdown>)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
  })
})
