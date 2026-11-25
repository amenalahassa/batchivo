// @vitest-environment node
/** An AI 3D draft is parsed Z-up and measured (spec 008, Q4). */
import { describe, expect, it } from 'vitest'

import { parseGlb } from './glb'

/** A one-triangle GLB: (0,0,0), (40,0,0), (0,30,0) in glTF's Y-up space. */
function triangleGlb(): ArrayBuffer {
  const positions = new Float32Array([0, 0, 0, 40, 0, 0, 0, 30, 0])
  const bin = new Uint8Array(positions.buffer)
  const json = JSON.stringify({
    asset: { version: '2.0' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
    buffers: [{ byteLength: bin.byteLength }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: bin.byteLength }],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: 3,
        type: 'VEC3',
        min: [0, 0, 0],
        max: [40, 30, 0],
      },
    ],
  })
  let jsonBytes = new TextEncoder().encode(json)
  const jsonPad = (4 - (jsonBytes.length % 4)) % 4
  if (jsonPad) {
    const padded = new Uint8Array(jsonBytes.length + jsonPad).fill(0x20)
    padded.set(jsonBytes)
    jsonBytes = padded
  }
  const total = 12 + 8 + jsonBytes.length + 8 + bin.byteLength
  const out = new ArrayBuffer(total)
  const view = new DataView(out)
  const bytes = new Uint8Array(out)
  view.setUint32(0, 0x46546c67, true)
  view.setUint32(4, 2, true)
  view.setUint32(8, total, true)
  view.setUint32(12, jsonBytes.length, true)
  view.setUint32(16, 0x4e4f534a, true)
  bytes.set(jsonBytes, 20)
  const binStart = 20 + jsonBytes.length
  view.setUint32(binStart, bin.byteLength, true)
  view.setUint32(binStart + 4, 0x004e4942, true)
  bytes.set(bin, binStart + 8)
  return out
}

describe('parseGlb', () => {
  it('turns Y-up into Z-up and measures the draft', async () => {
    const { size } = await parseGlb(triangleGlb())
    expect(size.x).toBeCloseTo(40)
    expect(size.y).toBeCloseTo(0)
    expect(size.z).toBeCloseTo(30)
  })

  it('refuses something that is not a GLB', async () => {
    await expect(parseGlb(new TextEncoder().encode('not a glb').buffer as ArrayBuffer)).rejects.toBeTruthy()
  })
})
