/**
 * What the parse worker does, as pure functions (spec 004, T039; research D6).
 *
 * Given a file's bytes and name, decide what can be shown: a mesh (.stl,
 * project .3mf) or toolpaths (.gcode, a plate of a .gcode.3mf). A .gcode.3mf
 * lists its plates (`Metadata/plate_N.gcode`); one that carries a mesh but no
 * plate G-code falls back to the mesh. Above the size limit only part of the
 * file is drawn and the result says so.
 */
import { unzipSync } from 'fflate'

import { MAX_SEGMENTS, parseGcode, type Toolpath } from '@/lib/viewer/gcode'
import { MAX_TRIANGLES, parse3mfMesh, parseStl, type MeshData } from '@/lib/viewer/mesh'

/** Files up to this size are drawn in full (research D6). */
export const FULL_PREVIEW_BYTES = 50 * 1024 * 1024

export interface ParseRequest {
  buffer: ArrayBuffer
  filename: string
  /** Plate to draw for a multi-plate .gcode.3mf; the first when absent. */
  plate?: number
}

export type ParseResult =
  | { kind: 'toolpath'; toolpath: Toolpath; plates: number[]; plate: number | null; reduced: boolean }
  | { kind: 'mesh'; mesh: MeshData; reduced: boolean }
  | { kind: 'empty'; message: string }

export const NOTHING_VIEWABLE =
  'Nothing in this file can be shown: it has neither a part nor a sliced plate.'

const decoder = new TextDecoder()

/** Plate numbers of a .gcode.3mf, in order. */
export function listPlates(names: string[]): number[] {
  const plates = new Set<number>()
  for (const name of names) {
    const m = name.match(/^Metadata\/plate_(\d+)\.gcode$/i)
    if (m) plates.add(Number(m[1]))
  }
  return [...plates].sort((a, b) => a - b)
}

/**
 * Segment and triangle caps for a file of this size. A large file keeps fewer
 * so the GPU and the phone stay responsive (FR-022).
 */
export function capsFor(bytes: number): { maxSegments: number; maxTriangles: number } {
  if (bytes <= FULL_PREVIEW_BYTES) return { maxSegments: MAX_SEGMENTS, maxTriangles: MAX_TRIANGLES }
  const share = FULL_PREVIEW_BYTES / bytes
  return {
    maxSegments: Math.max(100_000, Math.floor(MAX_SEGMENTS * share)),
    maxTriangles: Math.max(100_000, Math.floor(MAX_TRIANGLES * share)),
  }
}

export function parseModelFile({ buffer, filename, plate }: ParseRequest): ParseResult {
  const bytes = new Uint8Array(buffer)
  const name = filename.toLowerCase()
  const caps = capsFor(bytes.byteLength)
  const large = bytes.byteLength > FULL_PREVIEW_BYTES

  if (name.endsWith('.stl')) {
    const mesh = parseStl(bytes, caps.maxTriangles)
    if (mesh.triangleCount === 0) return { kind: 'empty', message: NOTHING_VIEWABLE }
    return { kind: 'mesh', mesh, reduced: mesh.reduced || large }
  }

  if (name.endsWith('.3mf')) {
    let files: Record<string, Uint8Array>
    try {
      files = unzipSync(bytes)
    } catch {
      return { kind: 'empty', message: "This file couldn't be opened as a 3MF package." }
    }
    const plates = listPlates(Object.keys(files))
    if (plates.length > 0) {
      const chosen = plate !== undefined && plates.includes(plate) ? plate : plates[0]
      const text = decoder.decode(files[`Metadata/plate_${chosen}.gcode`])
      const toolpath = parseGcode(text, { maxSegments: caps.maxSegments })
      return { kind: 'toolpath', toolpath, plates, plate: chosen, reduced: toolpath.reduced || large }
    }
    const mesh = parse3mfMesh(files, caps.maxTriangles)
    if (mesh) return { kind: 'mesh', mesh, reduced: mesh.reduced || large }
    return { kind: 'empty', message: NOTHING_VIEWABLE }
  }

  // Plain G-code.
  const toolpath = parseGcode(decoder.decode(bytes), { maxSegments: caps.maxSegments })
  if (toolpath.segmentCount === 0) return { kind: 'empty', message: NOTHING_VIEWABLE }
  return { kind: 'toolpath', toolpath, plates: [], plate: null, reduced: toolpath.reduced || large }
}

/** The buffers to transfer back to the page instead of copying them. */
export function transferables(result: ParseResult): ArrayBuffer[] {
  if (result.kind === 'toolpath') return [result.toolpath.positions.buffer as ArrayBuffer]
  if (result.kind === 'mesh') return [result.mesh.positions.buffer as ArrayBuffer]
  return []
}
