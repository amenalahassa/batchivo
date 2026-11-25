/**
 * A small G-code toolpath parser for the viewer (spec 004, research D5).
 *
 * Reads G0/G1 moves and G2/G3 arcs (flattened into short segments), absolute
 * and relative positioning (G90/G91), absolute and relative extrusion
 * (M82/M83), G92 resets, and layer changes (`;LAYER_CHANGE`, `; CHANGE_LAYER`,
 * or a new Z when the file has no markers). Only extruding moves are kept: a
 * travel move prints nothing, so it is not drawn.
 *
 * The output is one `Float32Array` of segments (six floats each: x1 y1 z1 x2
 * y2 z2, in the file's millimetres) ordered by layer, plus where each layer
 * starts, so the viewer draws layers 0..n with a single `drawRange`.
 *
 * Pure and DOM-free: it runs in the parse worker and in unit tests.
 */

export interface GcodeHeader {
  printerModel?: string
  filamentType?: string
  nozzleDiameter?: string
}

export interface ToolpathLayer {
  /** Height of the layer, in mm. */
  z: number
  /** Index of the layer's first segment. */
  start: number
  /** Number of segments in the layer. */
  count: number
}

export interface Toolpath {
  /** Six floats per segment. */
  positions: Float32Array
  segmentCount: number
  layers: ToolpathLayer[]
  header: GcodeHeader
  /** True when segments were dropped to stay under the cap (FR-022). */
  reduced: boolean
}

export interface ParseOptions {
  /** Most segments to keep; beyond it every Nth segment is kept. */
  maxSegments?: number
}

/** Above this many segments the preview is reduced (research D6). */
export const MAX_SEGMENTS = 2_000_000

const ARC_STEP_MM = 1
const HEADER_KEYS: Record<string, keyof GcodeHeader> = {
  printer_model: 'printerModel',
  filament_type: 'filamentType',
  nozzle_diameter: 'nozzleDiameter',
}

/** A Float32Array that grows as segments are added. */
class Segments {
  data = new Float32Array(6 * 4096)
  length = 0 // in segments

  push(x1: number, y1: number, z1: number, x2: number, y2: number, z2: number) {
    if ((this.length + 1) * 6 > this.data.length) {
      const next = new Float32Array(this.data.length * 2)
      next.set(this.data)
      this.data = next
    }
    const o = this.length * 6
    this.data[o] = x1
    this.data[o + 1] = y1
    this.data[o + 2] = z1
    this.data[o + 3] = x2
    this.data[o + 4] = y2
    this.data[o + 5] = z2
    this.length += 1
  }
}

/** Read the header comments the slicer writes (`; key = value` or `; key: value`). */
export function parseHeader(text: string, scanChars = 200_000): GcodeHeader {
  const header: GcodeHeader = {}
  const head = text.length > scanChars * 2 ? text.slice(0, scanChars) + '\n' + text.slice(-scanChars) : text
  const re = /^;\s*(printer_model|filament_type|nozzle_diameter)\s*[=:]\s*(.+?)\s*$/gm
  for (const match of head.matchAll(re)) {
    const key = HEADER_KEYS[match[1]]
    if (header[key] === undefined) {
      // Multi-extruder files list one value per extruder: the first is the one used.
      header[key] = match[2].split(/[;,]/)[0].trim()
    }
  }
  return header
}

function words(line: string): Map<string, number> {
  const out = new Map<string, number>()
  const re = /([A-Z])\s*(-?\d*\.?\d+(?:e-?\d+)?)/gi
  for (const m of line.matchAll(re)) out.set(m[1].toUpperCase(), Number(m[2]))
  return out
}

export function parseGcode(text: string, options: ParseOptions = {}): Toolpath {
  const maxSegments = options.maxSegments ?? MAX_SEGMENTS
  const segments = new Segments()
  const layerStarts: { z: number; start: number }[] = []

  let x = 0
  let y = 0
  let z = 0
  let e = 0
  let absolute = true
  let absoluteE = true
  let markersSeen = false
  let pendingLayer = false
  let layerZ: number | null = null

  const startLayerIfNeeded = () => {
    if (pendingLayer || layerZ === null || (!markersSeen && z !== layerZ)) {
      const last = layerStarts[layerStarts.length - 1]
      if (last && last.start === segments.length) {
        last.z = z // an empty layer: reuse it
      } else {
        layerStarts.push({ z, start: segments.length })
      }
      layerZ = z
      pendingLayer = false
    }
  }

  const lines = text.split('\n')
  for (const raw of lines) {
    const commentAt = raw.indexOf(';')
    if (commentAt >= 0) {
      const comment = raw.slice(commentAt + 1).trim().toUpperCase()
      if (comment === 'LAYER_CHANGE' || comment === 'CHANGE_LAYER') {
        markersSeen = true
        pendingLayer = true
      }
    }
    const code = (commentAt >= 0 ? raw.slice(0, commentAt) : raw).trim()
    if (!code) continue
    const head = code.split(/\s+/, 1)[0].toUpperCase()

    switch (head) {
      case 'G90':
        absolute = true
        absoluteE = true
        continue
      case 'G91':
        absolute = false
        absoluteE = false
        continue
      case 'M82':
        absoluteE = true
        continue
      case 'M83':
        absoluteE = false
        continue
      case 'G92': {
        const w = words(code.slice(3))
        if (w.has('X')) x = w.get('X')!
        if (w.has('Y')) y = w.get('Y')!
        if (w.has('Z')) z = w.get('Z')!
        if (w.has('E')) e = w.get('E')!
        continue
      }
    }

    const isLine = head === 'G0' || head === 'G1' || head === 'G00' || head === 'G01'
    const isArc = head === 'G2' || head === 'G3' || head === 'G02' || head === 'G03'
    if (!isLine && !isArc) continue

    const w = words(code.slice(head.length))
    const nx = w.has('X') ? (absolute ? w.get('X')! : x + w.get('X')!) : x
    const ny = w.has('Y') ? (absolute ? w.get('Y')! : y + w.get('Y')!) : y
    const nz = w.has('Z') ? (absolute ? w.get('Z')! : z + w.get('Z')!) : z
    let extrudes = false
    if (w.has('E')) {
      const value = w.get('E')!
      const delta = absoluteE ? value - e : value
      e = absoluteE ? value : e + value
      extrudes = delta > 0
    }
    const moves = nx !== x || ny !== y

    if (extrudes && moves) {
      z = nz
      startLayerIfNeeded()
      if (isArc && (w.has('I') || w.has('J'))) {
        flattenArc(segments, x, y, nx, ny, z, w.get('I') ?? 0, w.get('J') ?? 0, head.endsWith('2'))
      } else {
        segments.push(x, y, z, nx, ny, z)
      }
    }
    x = nx
    y = ny
    z = nz
  }

  const layers: ToolpathLayer[] = layerStarts.map((l, i) => ({
    z: l.z,
    start: l.start,
    count: (layerStarts[i + 1]?.start ?? segments.length) - l.start,
  }))
  const full: Toolpath = {
    positions: segments.data.subarray(0, segments.length * 6),
    segmentCount: segments.length,
    layers: layers.filter((l) => l.count > 0),
    header: parseHeader(text),
    reduced: false,
  }
  return full.segmentCount > maxSegments ? decimate(full, maxSegments) : full
}

/** Flatten an arc from (x1, y1) to (x2, y2) around (x1 + i, y1 + j). */
function flattenArc(
  out: Segments,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  z: number,
  i: number,
  j: number,
  clockwise: boolean
) {
  const cx = x1 + i
  const cy = y1 + j
  const r = Math.hypot(i, j)
  const a1 = Math.atan2(y1 - cy, x1 - cx)
  let a2 = Math.atan2(y2 - cy, x2 - cx)
  if (clockwise && a2 >= a1) a2 -= 2 * Math.PI
  if (!clockwise && a2 <= a1) a2 += 2 * Math.PI
  const sweep = a2 - a1
  const steps = Math.max(2, Math.ceil((Math.abs(sweep) * r) / ARC_STEP_MM))
  let px = x1
  let py = y1
  for (let s = 1; s <= steps; s++) {
    const a = a1 + (sweep * s) / steps
    const qx = s === steps ? x2 : cx + r * Math.cos(a)
    const qy = s === steps ? y2 : cy + r * Math.sin(a)
    out.push(px, py, z, qx, qy, z)
    px = qx
    py = qy
  }
}

/** Keep every Nth segment so the total stays under `max`, layer by layer. */
export function decimate(path: Toolpath, max: number): Toolpath {
  const step = Math.ceil(path.segmentCount / max)
  const positions = new Float32Array(Math.ceil(path.segmentCount / step) * 6 + path.layers.length * 6)
  let n = 0
  const layers: ToolpathLayer[] = []
  for (const layer of path.layers) {
    const start = n
    for (let s = layer.start; s < layer.start + layer.count; s += step) {
      positions.set(path.positions.subarray(s * 6, s * 6 + 6), n * 6)
      n += 1
    }
    layers.push({ z: layer.z, start, count: n - start })
  }
  return {
    ...path,
    positions: positions.subarray(0, n * 6),
    segmentCount: n,
    layers,
    reduced: true,
  }
}

/** Bounding box of a toolpath, in mm. */
export function toolpathBounds(path: Toolpath): { min: [number, number, number]; max: [number, number, number] } {
  const min: [number, number, number] = [Infinity, Infinity, Infinity]
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity]
  const p = path.positions
  for (let i = 0; i < p.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      if (p[i + k] < min[k]) min[k] = p[i + k]
      if (p[i + k] > max[k]) max[k] = p[i + k]
    }
  }
  return { min, max }
}

/**
 * What ToolpathView draws for a chosen layer, in vertices (two per segment):
 * every layer below it faint, the layer itself bright (FR-019).
 */
export function layerDrawRanges(
  path: Pick<Toolpath, 'layers'>,
  layer: number
): { below: [number, number]; top: [number, number] } {
  const current = path.layers[layer]
  if (!current) return { below: [0, 0], top: [0, 0] }
  return { below: [0, current.start * 2], top: [current.start * 2, current.count * 2] }
}
