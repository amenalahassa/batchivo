/**
 * @vitest-environment node
 *
 * What the parse worker shows for each kind of file (spec 004, T036).
 */
import { describe, expect, it } from 'vitest'

import { capsFor, FULL_PREVIEW_BYTES, listPlates, NOTHING_VIEWABLE, parseModelFile } from './modelParse'
import { meshBounds, parse3mfMesh } from '@/lib/viewer/mesh'
import {
  binaryStl,
  cubeModelXml,
  emptyGcode3mf,
  meshOnlyGcode3mf,
  plainGcode,
  projectCube3mf,
  slicedTwoPlates,
  strToU8,
  toBuffer,
} from '@/test/fixtures/modelFiles'

describe('parseModelFile', () => {
  it('lists the plates of a sliced .gcode.3mf and draws the first', () => {
    const result = parseModelFile({ buffer: toBuffer(slicedTwoPlates()), filename: 'part.gcode.3mf' })
    expect(result.kind).toBe('toolpath')
    if (result.kind !== 'toolpath') return
    expect(result.plates).toEqual([1, 2])
    expect(result.plate).toBe(1)
    expect(result.toolpath.segmentCount).toBe(5)
    expect(result.toolpath.header.printerModel).toBe('Bambu Lab A1')
  })

  it('draws the plate asked for', () => {
    const result = parseModelFile({ buffer: toBuffer(slicedTwoPlates()), filename: 'part.gcode.3mf', plate: 2 })
    expect(result.kind === 'toolpath' && result.toolpath.segmentCount).toBe(1)
  })

  it('falls back to the mesh of a .gcode.3mf without plate G-code', () => {
    const result = parseModelFile({ buffer: toBuffer(meshOnlyGcode3mf()), filename: 'part.gcode.3mf' })
    expect(result.kind).toBe('mesh')
    expect(result.kind === 'mesh' && result.mesh.triangleCount).toBe(12)
  })

  it('says when a file holds nothing viewable', () => {
    expect(parseModelFile({ buffer: toBuffer(emptyGcode3mf()), filename: 'x.gcode.3mf' })).toEqual({
      kind: 'empty',
      message: NOTHING_VIEWABLE,
    })
  })

  it('reads a project 3MF mesh with its build transform', () => {
    const result = parseModelFile({
      buffer: toBuffer(projectCube3mf('1 0 0 0 1 0 0 0 1 100 50 0')),
      filename: 'part.3mf',
    })
    expect(result.kind).toBe('mesh')
    if (result.kind !== 'mesh') return
    expect(meshBounds(result.mesh)).toEqual({ min: [100, 50, 0], max: [110, 60, 10] })
  })

  it('follows components into other model parts, as Bambu projects do', () => {
    const root = `<?xml version="1.0"?>
<model xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">
  <resources><object id="5"><components>
    <component p:path="/3D/Objects/object_1.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 5"/>
  </components></object></resources>
  <build><item objectid="5" transform="2 0 0 0 2 0 0 0 2 0 0 0"/></build>
</model>`
    const mesh = parse3mfMesh({
      '3D/3dmodel.model': strToU8(root),
      '3D/Objects/object_1.model': strToU8(cubeModelXml()),
    })
    expect(mesh && meshBounds(mesh)).toEqual({ min: [0, 0, 10], max: [20, 20, 30] })
  })

  it('caps a mesh at the triangle limit and says it is reduced', () => {
    const { maxTriangles } = capsFor(0)
    expect(maxTriangles).toBe(1_500_000)
    const result = parseModelFile({ buffer: toBuffer(binaryStl(3000)), filename: 'big.stl' })
    expect(result.kind === 'mesh' && result.reduced).toBe(false)
  })

  it('draws plain G-code', () => {
    const result = parseModelFile({ buffer: toBuffer(strToU8(plainGcode())), filename: 'p.gcode' })
    expect(result.kind === 'toolpath' && result.toolpath.layers.length).toBe(3)
  })

  it('lowers the caps above the full-preview size', () => {
    const caps = capsFor(FULL_PREVIEW_BYTES * 4)
    expect(caps.maxSegments).toBeLessThan(2_000_000)
    expect(caps.maxTriangles).toBeLessThan(1_500_000)
  })
})

describe('listPlates', () => {
  it('reads plate numbers in order and ignores other files', () => {
    expect(
      listPlates(['Metadata/plate_10.gcode', 'Metadata/plate_2.gcode', 'Metadata/plate_2.png', '3D/3dmodel.model']),
    ).toEqual([2, 10])
  })
})
