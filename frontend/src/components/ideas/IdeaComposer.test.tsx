/** The composer: text entries, images by picker, drop and paste, iterations (spec 007, T034). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'

import { fireEvent, render, screen, waitFor } from '@/test/test-utils'

import { IdeaComposer } from './IdeaComposer'

const api = vi.hoisted(() => ({
  createEntry: vi.fn(),
  uploadImages: vi.fn(),
  startIteration: vi.fn(),
}))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))

const png = (name: string) => new File(['x'], name, { type: 'image/png' })

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  api.uploadImages.mockResolvedValue({ created: [], refused: [] })
  api.createEntry.mockResolvedValue({})
  api.startIteration.mockResolvedValue({ items: [], current_iteration: 2 })
})

function composer() {
  render(<IdeaComposer ideaId="idea-1" currentIteration={1} />)
  return screen.getByTestId('idea-composer')
}

describe('IdeaComposer', () => {
  it('adds a note', async () => {
    composer()
    await userEvent.type(screen.getByLabelText('Entry text'), 'Try 2 mm walls')
    await userEvent.click(screen.getByRole('button', { name: 'Add note' }))
    expect(api.createEntry).toHaveBeenCalledWith('idea-1', {
      kind: 'note',
      body: 'Try 2 mm walls',
      link_url: null,
    })
  })

  it('adds a link and refuses one without a link', async () => {
    composer()
    await userEvent.click(screen.getByRole('tab', { name: 'Link' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add link' }))
    expect(screen.getByRole('alert')).toHaveTextContent('A link entry needs a link')
    await userEvent.type(screen.getByLabelText('Link'), 'https://example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Add link' }))
    expect(api.createEntry).toHaveBeenCalledWith(
      'idea-1',
      expect.objectContaining({ kind: 'link', link_url: 'https://example.com' })
    )
  })

  it('uploads a pasted image', async () => {
    const zone = composer()
    fireEvent.paste(zone, { clipboardData: { files: [png('pasted.png')] } })
    await waitFor(() =>
      expect(api.uploadImages).toHaveBeenCalledWith('idea-1', [expect.any(File)], 'image')
    )
  })

  it('leaves pasted text to the text box', () => {
    const zone = composer()
    fireEvent.paste(zone, { clipboardData: { files: [], getData: () => 'text' } })
    expect(api.uploadImages).not.toHaveBeenCalled()
  })

  it('uploads two dropped files as sketches when asked', async () => {
    const zone = composer()
    await userEvent.selectOptions(screen.getByLabelText('Image kind'), 'sketch')
    fireEvent.drop(zone, { dataTransfer: { files: [png('a.png'), png('b.png')] } })
    await waitFor(() => expect(api.uploadImages).toHaveBeenCalled())
    const [, files, kind] = api.uploadImages.mock.calls[0]
    expect(files).toHaveLength(2)
    expect(kind).toBe('sketch')
  })

  it('uploads files from the picker', async () => {
    composer()
    await userEvent.upload(screen.getByLabelText('Image files'), [png('a.png')])
    await waitFor(() => expect(api.uploadImages).toHaveBeenCalled())
  })

  it('lists each refused file with its reason', async () => {
    api.uploadImages.mockResolvedValue({
      created: [{}],
      refused: [{ filename: 'big.png', reason: 'File too large (max 10 MB)' }],
    })
    const zone = composer()
    fireEvent.drop(zone, { dataTransfer: { files: [png('ok.png'), png('big.png')] } })
    expect(await screen.findByLabelText('Refused files')).toHaveTextContent(
      'big.png: File too large (max 10 MB)'
    )
  })

  it('lists refused files when the server refused them all', async () => {
    const response = {
      status: 422,
      statusText: 'Unprocessable',
      headers: {},
      config: { headers: new AxiosHeaders() },
      data: {
        detail: {
          message: 'No image was saved',
          refused: [{ filename: 'notes.txt', reason: 'Unsupported file type' }],
        },
      },
    }
    api.uploadImages.mockRejectedValue(
      new AxiosError('422', 'ERR_BAD_REQUEST', undefined, undefined, response)
    )
    const zone = composer()
    fireEvent.drop(zone, { dataTransfer: { files: [png('notes.txt')] } })
    expect(await screen.findByLabelText('Refused files')).toHaveTextContent(
      'notes.txt: Unsupported file type'
    )
  })

  it('starts the next iteration with a note', async () => {
    composer()
    await userEvent.click(screen.getByRole('button', { name: 'Start next iteration' }))
    await userEvent.type(screen.getByLabelText('Note (optional)'), 'Thicker clip')
    await userEvent.click(screen.getByRole('button', { name: 'Start iteration' }))
    expect(api.startIteration).toHaveBeenCalledWith('idea-1', 'Thicker clip')
  })

  it('has room for actions from later features', () => {
    render(
      <IdeaComposer ideaId="idea-1" currentIteration={1} extraActions={<button>Generate</button>} />
    )
    expect(screen.getByRole('button', { name: 'Generate' })).toBeInTheDocument()
  })
})
