/**
 * Fetch a model file and parse it in the worker (spec 004, research D6).
 *
 * The file comes through the existing download endpoint as an ArrayBuffer and
 * is transferred to the worker, so the page keeps responding while a large
 * file is read (FR-022).
 */
import { getModelFileDownloadUrl } from '@/lib/api/models'
import { getAuthTokens } from '@/lib/auth'
import type { ParseResult } from '@/workers/modelParse'
import type { WorkerReply } from '@/workers/modelParse.worker'

export async function fetchModelFile(modelId: string, fileId: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const token = getAuthTokens()?.accessToken
  const response = await fetch(getModelFileDownloadUrl(modelId, fileId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  })
  if (!response.ok) throw new Error(`The file could not be downloaded (server returned ${response.status})`)
  return response.arrayBuffer()
}

let nextId = 1

/** Parse in a fresh worker; it is ended once it answers. */
export function parseInWorker(buffer: ArrayBuffer, filename: string, plate?: number): Promise<ParseResult> {
  const worker = new Worker(new URL('../../workers/modelParse.worker.ts', import.meta.url), {
    type: 'module',
  })
  const id = nextId++
  return new Promise<ParseResult>((resolve, reject) => {
    worker.onmessage = (event: MessageEvent<WorkerReply>) => {
      if (event.data.id !== id) return
      worker.terminate()
      if ('error' in event.data) reject(new Error(event.data.error))
      else resolve(event.data.result)
    }
    worker.onerror = (event) => {
      worker.terminate()
      reject(new Error(event.message || 'The file could not be read'))
    }
    // The buffer is kept by the caller for re-parsing another plate, so it is copied, not moved.
    worker.postMessage({ id, buffer, filename, plate })
  })
}
