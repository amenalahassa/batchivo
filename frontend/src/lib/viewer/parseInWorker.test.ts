/**
 * @vitest-environment node
 *
 * Fetching a model file and handing it to the parse worker (spec 004, T062; FR-022).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/auth', () => ({ getAuthTokens: () => ({ accessToken: 'tok' }) }))
vi.mock('@/lib/api/models', () => ({
  getModelFileDownloadUrl: (m: string, f: string) => `/api/v1/models/${m}/files/${f}/download`,
}))

import { fetchModelFile, parseInWorker } from './parseInWorker'

class FakeWorker {
  static last: FakeWorker
  onmessage: ((e: { data: unknown }) => void) | null = null
  onerror: ((e: { message: string }) => void) | null = null
  posted: unknown
  terminated = false
  constructor() {
    FakeWorker.last = this
  }
  postMessage(data: unknown) {
    this.posted = data
  }
  terminate() {
    this.terminated = true
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchModelFile', () => {
  it('downloads with the bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => new ArrayBuffer(4) })
    vi.stubGlobal('fetch', fetchMock)
    const buffer = await fetchModelFile('m1', 'f1')
    expect(buffer.byteLength).toBe(4)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/models/m1/files/f1/download', expect.objectContaining({
      headers: { Authorization: 'Bearer tok' },
    }))
  })

  it('says when the download fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    await expect(fetchModelFile('m1', 'f1')).rejects.toThrow('server returned 404')
  })
})

describe('parseInWorker', () => {
  it('posts the file to a worker and resolves with its answer, then ends it', async () => {
    vi.stubGlobal('Worker', FakeWorker)
    const buffer = new ArrayBuffer(8)
    const pending = parseInWorker(buffer, 'two.gcode.3mf', 2)
    const worker = FakeWorker.last
    const sent = worker.posted as { id: number; filename: string; plate: number; buffer: ArrayBuffer }
    expect([sent.filename, sent.plate, sent.buffer]).toEqual(['two.gcode.3mf', 2, buffer])
    worker.onmessage?.({ data: { id: sent.id + 1000, result: { kind: 'empty', message: 'stale' } } })
    worker.onmessage?.({ data: { id: sent.id, result: { kind: 'empty', message: 'nothing' } } })
    await expect(pending).resolves.toEqual({ kind: 'empty', message: 'nothing' })
    expect(worker.terminated).toBe(true)
  })

  it('rejects with the worker\'s error', async () => {
    vi.stubGlobal('Worker', FakeWorker)
    const pending = parseInWorker(new ArrayBuffer(1), 'x.stl')
    const worker = FakeWorker.last
    worker.onmessage?.({ data: { id: (worker.posted as { id: number }).id, error: 'bad file' } })
    await expect(pending).rejects.toThrow('bad file')
  })

  it('rejects when the worker itself fails', async () => {
    vi.stubGlobal('Worker', FakeWorker)
    const pending = parseInWorker(new ArrayBuffer(1), 'x.stl')
    FakeWorker.last.onerror?.({ message: 'crashed' })
    await expect(pending).rejects.toThrow('crashed')
  })
})
