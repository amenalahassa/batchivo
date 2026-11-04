/**
 * Mesh parsing for the viewer (spec 004, research D5/D6).
 *
 * STL (binary and ASCII) and 3MF meshes become one flat triangle list, nine
 * floats per triangle, in the file's millimetres. Written without three's
 * loaders: three's 3MFLoader needs `DOMParser`, which a Web Worker does not
 * have, and this keeps the worker free of three.js altogether.
 *
 * 3MF: every `<object>` with a `<mesh>` is read from every model part of the
 * package (Bambu projects keep the meshes in `3D/Objects/*.model` and point at
 * them through `<component p:path=…>`), placed by the build items' and
 * components' transforms.
 */

export interface MeshData {
  /** Nine floats per triangle. */
  positions: Float32Array
  triangleCount: number
  /** True when triangles were dropped to stay under the cap (FR-022). */
  reduced: boolean
}

/** Above this many triangles the preview is reduced (research D6). */
export const MAX_TRIANGLES = 1_500_000

const decoder = new TextDecoder()

function isBinaryStl(bytes: Uint8Array): boolean {
  if (bytes.length < 84) return false
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const count = view.getUint32(80, true)
  if (84 + count * 50 === bytes.length) return true
  const start = decoder.decode(bytes.subarray(0, 5)).toLowerCase()
  return start !== 'solid'
}

export function parseStl(bytes: Uint8Array, maxTriangles = MAX_TRIANGLES): MeshData {
  if (isBinaryStl(bytes)) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const count = Math.min(view.getUint32(80, true), Math.floor((bytes.length - 84) / 50))
    const step = Math.max(1, Math.ceil(count / maxTriangles))
    const kept = Math.ceil(count / step)
    const positions = new Float32Array(kept * 9)
    let n = 0
    for (let t = 0; t < count; t += step) {
      const o = 84 + t * 50 + 12 // skip the facet normal
      for (let k = 0; k < 9; k++) positions[n * 9 + k] = view.getFloat32(o + k * 4, true)
      n += 1
    }
    return { positions: positions.subarray(0, n * 9), triangleCount: n, reduced: step > 1 }
  }
  const text = decoder.decode(bytes)
  const values: number[] = []
  for (const m of text.matchAll(/vertex\s+(\S+)\s+(\S+)\s+(\S+)/g)) {
    values.push(Number(m[1]), Number(m[2]), Number(m[3]))
  }
  return capTriangles(new Float32Array(values), maxTriangles)
}

function capTriangles(all: Float32Array, maxTriangles: number): MeshData {
  const count = Math.floor(all.length / 9)
  if (count <= maxTriangles) return { positions: all.subarray(0, count * 9), triangleCount: count, reduced: false }
  const step = Math.ceil(count / maxTriangles)
  const positions = new Float32Array(Math.ceil(count / step) * 9)
  let n = 0
  for (let t = 0; t < count; t += step) {
    positions.set(all.subarray(t * 9, t * 9 + 9), n * 9)
    n += 1
  }
  return { positions: positions.subarray(0, n * 9), triangleCount: n, reduced: true }
}

// ---------------------------------------------------------------------------
// 3MF
// ---------------------------------------------------------------------------

/** A 3MF affine transform: 12 numbers, row-major 4x3 (m00 m01 m02 m10 … m32). */
type Transform = number[]
const IDENTITY: Transform = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]

function parseTransform(value: string | undefined): Transform {
  if (!value) return IDENTITY
  const parts = value.trim().split(/\s+/).map(Number)
  return parts.length === 12 && parts.every(Number.isFinite) ? parts : IDENTITY
}

/** a then b (3MF row-vector convention: p' = p · a · b). */
function compose(a: Transform, b: Transform): Transform {
  const m = (t: Transform, r: number, c: number) => t[r * 3 + c]
  const out: number[] = []
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 3; c++) {
      let v = r === 3 ? m(b, 3, c) : 0
      for (let k = 0; k < 3; k++) v += m(a, r, k) * m(b, k, c)
      out.push(v)
    }
  }
  return out
}

function apply(t: Transform, x: number, y: number, z: number): [number, number, number] {
  return [
    x * t[0] + y * t[3] + z * t[6] + t[9],
    x * t[1] + y * t[4] + z * t[7] + t[10],
    x * t[2] + y * t[5] + z * t[8] + t[11],
  ]
}

function attr(tag: string, name: string): string | undefined {
  const m = tag.match(new RegExp(`(?:^|\\s)${name.replace(':', '\\:')}\\s*=\\s*"([^"]*)"`))
  return m?.[1]
}

interface ObjectDef {
  vertices?: Float32Array
  triangles?: Uint32Array
  components: { objectId: string; path?: string; transform: Transform }[]
}

/** Objects of one model part, keyed by id. */
export function parseModelXml(xml: string): { objects: Map<string, ObjectDef>; build: { objectId: string; path?: string; transform: Transform }[] } {
  const objects = new Map<string, ObjectDef>()
  for (const obj of xml.matchAll(/<object\b([^>]*)>([\s\S]*?)<\/object>/g)) {
    const id = attr(obj[1], 'id')
    if (!id) continue
    const body = obj[2]
    const def: ObjectDef = { components: [] }
    const mesh = body.match(/<mesh\b[^>]*>([\s\S]*?)<\/mesh>/)
    if (mesh) {
      const verts: number[] = []
      for (const v of mesh[1].matchAll(/<vertex\b([^>]*)\/?>/g)) {
        verts.push(Number(attr(v[1], 'x')), Number(attr(v[1], 'y')), Number(attr(v[1], 'z')))
      }
      const tris: number[] = []
      for (const t of mesh[1].matchAll(/<triangle\b([^>]*)\/?>/g)) {
        tris.push(Number(attr(t[1], 'v1')), Number(attr(t[1], 'v2')), Number(attr(t[1], 'v3')))
      }
      def.vertices = new Float32Array(verts)
      def.triangles = new Uint32Array(tris)
    }
    for (const c of body.matchAll(/<component\b([^>]*)\/?>/g)) {
      const objectId = attr(c[1], 'objectid')
      if (objectId) {
        def.components.push({
          objectId,
          path: attr(c[1], 'p:path'),
          transform: parseTransform(attr(c[1], 'transform')),
        })
      }
    }
    objects.set(id, def)
  }
  const build: { objectId: string; path?: string; transform: Transform }[] = []
  const buildBody = xml.match(/<build\b[^>]*>([\s\S]*?)<\/build>/)
  if (buildBody) {
    for (const item of buildBody[1].matchAll(/<item\b([^>]*)\/?>/g)) {
      const objectId = attr(item[1], 'objectid')
      if (objectId) {
        build.push({ objectId, path: attr(item[1], 'p:path'), transform: parseTransform(attr(item[1], 'transform')) })
      }
    }
  }
  return { objects, build }
}

/**
 * The mesh of a 3MF package, given its unzipped parts.
 *
 * Returns null when no part holds a mesh (a sliced `.gcode.3mf`).
 */
export function parse3mfMesh(files: Record<string, Uint8Array>, maxTriangles = MAX_TRIANGLES): MeshData | null {
  const parts = new Map<string, ReturnType<typeof parseModelXml>>()
  const norm = (p: string) => p.replace(/^\//, '')
  for (const [name, bytes] of Object.entries(files)) {
    if (name.toLowerCase().endsWith('.model')) parts.set(norm(name), parseModelXml(decoder.decode(bytes)))
  }
  const root = parts.get('3D/3dmodel.model') ?? [...parts.values()][0]
  if (!root) return null

  const out: number[] = []
  const emit = (partPath: string, objectId: string, transform: Transform, depth: number) => {
    if (depth > 8) return
    const part = parts.get(partPath)
    const obj = part?.objects.get(objectId)
    if (!obj) return
    if (obj.vertices && obj.triangles) {
      const v = obj.vertices
      const t = obj.triangles
      for (let i = 0; i < t.length; i++) {
        const k = t[i] * 3
        out.push(...apply(transform, v[k], v[k + 1], v[k + 2]))
      }
    }
    for (const c of obj.components) {
      emit(c.path ? norm(c.path) : partPath, c.objectId, compose(c.transform, transform), depth + 1)
    }
  }

  const rootPath = parts.has('3D/3dmodel.model') ? '3D/3dmodel.model' : [...parts.keys()][0]
  const items = root.build.length > 0 ? root.build : [...root.objects.keys()].map((objectId) => ({ objectId, path: undefined, transform: IDENTITY }))
  for (const item of items) emit(item.path ? norm(item.path) : rootPath, item.objectId, item.transform, 0)

  if (out.length === 0) return null
  return capTriangles(new Float32Array(out), maxTriangles)
}

/** Bounding box of a mesh, in mm. */
export function meshBounds(mesh: MeshData): { min: [number, number, number]; max: [number, number, number] } {
  const min: [number, number, number] = [Infinity, Infinity, Infinity]
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity]
  const p = mesh.positions
  for (let i = 0; i < p.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      if (p[i + k] < min[k]) min[k] = p[i + k]
      if (p[i + k] > max[k]) max[k] = p[i + k]
    }
  }
  return { min, max }
}
