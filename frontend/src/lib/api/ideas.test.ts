/**
 * @vitest-environment node
 *
 * The ideas client sends what FastAPI reads (spec 007, contracts/ideas-api.md).
 * No DOM needed: Node has FormData and File.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api'
import { ideasApi } from './ideas'

vi.mock('../api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

const client = vi.mocked(apiClient)

beforeEach(() => vi.clearAllMocks())

describe('ideasApi.list', () => {
  it('repeats status and tag, and drops empty values', async () => {
    client.get.mockResolvedValue({ items: [], total: 0, skip: 0, limit: 20 })
    await ideasApi.list({
      status: ['inbox', 'ready'],
      tag: ['car', 'clip'],
      search: '',
      source: undefined,
      sort: 'score',
      limit: 20,
    })
    const [url, config] = client.get.mock.calls[0]
    expect(url).toBe('/api/v1/ideas')
    const params = (config as { params: URLSearchParams }).params
    expect(params.getAll('status')).toEqual(['inbox', 'ready'])
    expect(params.getAll('tag')).toEqual(['car', 'clip'])
    expect(params.has('search')).toBe(false)
    expect(params.has('source')).toBe(false)
    expect(params.toString()).toBe('status=inbox&status=ready&tag=car&tag=clip&sort=score&limit=20')
  })
})

describe('ideasApi writes', () => {
  it('uploads every file under `files` with the kind', async () => {
    client.post.mockResolvedValue({ created: [], refused: [] })
    const files = [
      new File(['a'], 'a.png', { type: 'image/png' }),
      new File(['b'], 'b.png', { type: 'image/png' }),
    ]
    await ideasApi.uploadImages('idea-1', files, 'sketch')
    const [url, form, config] = client.post.mock.calls[0]
    expect(url).toBe('/api/v1/ideas/idea-1/entries/images')
    expect((form as FormData).getAll('files').map((f) => (f as File).name)).toEqual([
      'a.png',
      'b.png',
    ])
    expect((form as FormData).get('kind')).toBe('sketch')
    expect(config).toMatchObject({ headers: { 'Content-Type': 'multipart/form-data' } })
  })

  it('restores an idea by un-archiving it', async () => {
    await ideasApi.restore('idea-1')
    expect(client.patch).toHaveBeenCalledWith('/api/v1/ideas/idea-1', { archived: false })
  })

  it('sends a blank iteration note as none', async () => {
    await ideasApi.startIteration('idea-1', '')
    expect(client.post).toHaveBeenCalledWith('/api/v1/ideas/idea-1/iterations', { note: null })
  })

  it('previews an import as a dry run', async () => {
    await ideasApi.importItems([{ title: 'x' }], true)
    expect(client.post).toHaveBeenCalledWith('/api/v1/ideas/import', {
      items: [{ title: 'x' }],
      dry_run: true,
    })
  })

  it('reads entries with archived ones only when asked', async () => {
    await ideasApi.listEntries('idea-1')
    await ideasApi.listEntries('idea-1', true)
    expect(client.get.mock.calls[0][1]).toEqual({ params: undefined })
    expect(client.get.mock.calls[1][1]).toEqual({ params: { archived: true } })
  })
})

describe('ideasApi.getImageBlob', () => {
  it('fetches the image with the session, as a blob', async () => {
    const path = '/api/v1/ideas/i/entries/e/image?variant=thumb'
    await ideasApi.getImageBlob(path)
    expect(client.get).toHaveBeenCalledWith(path, { responseType: 'blob' })
  })
})
