/**
 * Parses a model file off the main thread (spec 004, T039; FR-022).
 *
 * Receives the file's bytes and name, answers with a mesh or toolpaths whose
 * buffers are transferred, not copied.
 */
import { parseModelFile, transferables, type ParseRequest, type ParseResult } from './modelParse'

export type WorkerReply = { id: number; result: ParseResult } | { id: number; error: string }

self.onmessage = (event: MessageEvent<ParseRequest & { id: number }>) => {
  const { id, ...request } = event.data
  try {
    const result = parseModelFile(request)
    // Transfer the result buffers; a subarray's buffer may be larger, so copy when needed.
    const reply: WorkerReply = { id, result: compact(result) }
    ;(self as unknown as Worker).postMessage(reply, transferables((reply as { result: ParseResult }).result))
  } catch (err) {
    ;(self as unknown as Worker).postMessage({
      id,
      error: err instanceof Error ? err.message : 'The file could not be read',
    } satisfies WorkerReply)
  }
}

/** Trim views to their own buffers so only the needed bytes cross. */
function compact(result: ParseResult): ParseResult {
  if (result.kind === 'toolpath') {
    return { ...result, toolpath: { ...result.toolpath, positions: result.toolpath.positions.slice() } }
  }
  if (result.kind === 'mesh') {
    return { ...result, mesh: { ...result.mesh, positions: result.mesh.positions.slice() } }
  }
  return result
}
