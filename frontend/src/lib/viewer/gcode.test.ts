/**
 * @vitest-environment node
 *
 * The viewer's G-code parser (spec 004, T035; research D5/D6).
 */
import { describe, expect, it } from 'vitest'

import { decimate, layerDrawRanges, parseGcode, parseHeader } from './gcode'
import { plainGcode } from '@/test/fixtures/modelFiles'

const seg = (path: ReturnType<typeof parseGcode>, i: number) =>
  Array.from(path.positions.subarray(i * 6, i * 6 + 6)).map((v) => Math.round(v * 1000) / 1000)

describe('parseGcode', () => {
  it('keeps extruding moves and drops travel', () => {
    const path = parseGcode(plainGcode())
    // 2 + 2 + 1 extruding moves; the G0 travel to (50, 50) is not drawn.
    expect(path.segmentCount).toBe(5)
    expect(seg(path, 0)).toEqual([10, 10, 0.2, 30, 10, 0.2])
    // The travel itself (30, 30) -> (50, 50) is not a segment; the next stroke starts from it.
    const all = Array.from({ length: path.segmentCount }, (_, i) => seg(path, i))
    expect(all).not.toContainEqual([30, 30, 0.2, 50, 50, 0.2])
    expect(all[2]).toEqual([50, 50, 0.4, 10, 30, 0.4])
  })

  it('splits layers on the slicer markers', () => {
    const path = parseGcode(plainGcode())
    expect(path.layers.map((l) => [l.z, l.start, l.count])).toEqual([
      [0.2, 0, 2],
      [0.4, 2, 2],
      [0.6, 4, 1],
    ])
  })

  it('splits layers on a new Z when the file has no markers', () => {
    const path = parseGcode('G90\nM82\nG1 Z0.2\nG1 X1 Y0 E1\nG1 Z0.4\nG1 X2 Y0 E2\nG1 X3 Y0 E3\n')
    expect(path.layers.map((l) => [l.z, l.count])).toEqual([
      [0.2, 1],
      [0.4, 2],
    ])
  })

  it('follows relative positioning and absolute extrusion', () => {
    const path = parseGcode('G91\nG1 Z0.2\nG1 X5 E1\nG1 X5 E1\nG90\nM82\nG92 E0\nG1 X0 Y0 E0.5\nG1 X1 Y0 E0.5\n')
    expect(seg(path, 0)).toEqual([0, 0, 0.2, 5, 0, 0.2])
    expect(seg(path, 1)).toEqual([5, 0, 0.2, 10, 0, 0.2])
    // After G92 E0 an absolute E of 0.5 extrudes; the next 0.5 does not.
    expect(seg(path, 2)).toEqual([10, 0, 0.2, 0, 0, 0.2])
    expect(path.segmentCount).toBe(3)
  })

  it('flattens arcs into short segments ending where the arc ends', () => {
    // A half circle of radius 10 from (0, 0) to (20, 0) around (10, 0).
    const path = parseGcode('G90\nM83\nG1 Z0.2\nG1 X0 Y0\nG2 X20 Y0 I10 J0 E2\n')
    expect(path.segmentCount).toBeGreaterThan(10)
    const last = seg(path, path.segmentCount - 1)
    expect(last.slice(3)).toEqual([20, 0, 0.2])
    // Clockwise from (0, 0) around (10, 0) passes through (10, 10).
    const ys = Array.from({ length: path.segmentCount }, (_, i) => seg(path, i)[4])
    expect(Math.max(...ys)).toBeCloseTo(10, 0)
  })

  it('reads the printer, filament and nozzle from the header', () => {
    expect(parseHeader(plainGcode())).toEqual({
      printerModel: 'Bambu Lab A1',
      filamentType: 'PLA',
      nozzleDiameter: '0.4',
    })
    expect(parseGcode(plainGcode()).header.printerModel).toBe('Bambu Lab A1')
  })

  it('keeps at most the cap, layer by layer, and says it is reduced', () => {
    const lines = ['G90', 'M83', ';LAYER_CHANGE', 'G1 Z0.2', 'G1 X0 Y0']
    for (let i = 1; i <= 1000; i++) lines.push(`G1 X${i} Y0 E0.1`)
    lines.push(';LAYER_CHANGE', 'G1 Z0.4')
    for (let i = 1; i <= 1000; i++) lines.push(`G1 X${1000 - i} Y0 E0.1`)
    const path = parseGcode(lines.join('\n'), { maxSegments: 300 })
    expect(path.reduced).toBe(true)
    expect(path.segmentCount).toBeLessThanOrEqual(300)
    expect(path.layers).toHaveLength(2)
    expect(path.layers[1].start).toBe(path.layers[0].count)
    expect(parseGcode(lines.join('\n')).reduced).toBe(false)
  })

  it('decimate is a no-loss copy at step 1', () => {
    const path = parseGcode(plainGcode())
    const same = decimate(path, 1000)
    expect(same.segmentCount).toBe(path.segmentCount)
  })
})

describe('layerDrawRanges', () => {
  const path = parseGcode(plainGcode())

  it('draws the layers below faint and the chosen layer bright, in vertices', () => {
    expect(layerDrawRanges(path, 1)).toEqual({ below: [0, 4], top: [4, 4] })
    expect(layerDrawRanges(path, 0)).toEqual({ below: [0, 0], top: [0, 4] })
  })

  it('draws nothing for a layer that does not exist', () => {
    expect(layerDrawRanges(path, 9)).toEqual({ below: [0, 0], top: [0, 0] })
  })
})
