/**
 * Model files for the viewer tests (spec 004, T003), built in code like the
 * backend's `tests/fixtures/model_files.py` so each says what it is.
 */
import { zipSync } from 'fflate'

/**
 * ASCII text as bytes. Not fflate's `strToU8`: under jsdom its TextEncoder
 * returns another realm's Uint8Array, which `zipSync` then takes for a folder.
 */
export const strToU8 = (text: string) => Uint8Array.from(text, (c) => c.charCodeAt(0))

export const GCODE_HEADER = `; HEADER_BLOCK_START
; BambuStudio 02.00.00.00
; total estimated time: 1h 58m 0s
; HEADER_BLOCK_END
; CONFIG_BLOCK_START
; printer_model = Bambu Lab A1
; filament_type = PLA;PLA
; nozzle_diameter = 0.4
; CONFIG_BLOCK_END
`

/** Three layers: a square perimeter, then two more strokes, with a travel between. */
export const GCODE_BODY = `G90
M83
G1 Z0.2 F600
;LAYER_CHANGE
G1 X10 Y10 F3000
G1 X30 Y10 E1.0
G1 X30 Y30 E1.0
G0 X50 Y50
;LAYER_CHANGE
G1 Z0.4
G1 X10 Y30 E1.0
G1 X10 Y10 E1.0
;LAYER_CHANGE
G1 Z0.6
G1 X20 Y20 E0.5
`

export function plainGcode(): string {
  return GCODE_HEADER + GCODE_BODY
}

const EMPTY_BUILD = `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources/>
  <build/>
</model>`

/** A 10 mm cube as 3MF XML: 8 vertices, 12 triangles. */
export function cubeModelXml(transform?: string): string {
  const v = [
    [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
    [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10],
  ]
  const t = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
  ]
  return `<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model"><mesh>
      <vertices>${v.map(([x, y, z]) => `<vertex x="${x}" y="${y}" z="${z}"/>`).join('')}</vertices>
      <triangles>${t.map(([a, b, c]) => `<triangle v1="${a}" v2="${b}" v3="${c}"/>`).join('')}</triangles>
    </mesh></object>
  </resources>
  <build><item objectid="1"${transform ? ` transform="${transform}"` : ''}/></build>
</model>`
}

/** A Bambu `.gcode.3mf`: plate G-code and slice info, no mesh in the build. */
export function slicedTwoPlates(): Uint8Array {
  return zipSync({
    '[Content_Types].xml': strToU8('<Types/>'),
    '3D/3dmodel.model': strToU8(EMPTY_BUILD),
    'Metadata/slice_info.config': strToU8('<config/>'),
    'Metadata/plate_1.gcode': strToU8(plainGcode()),
    'Metadata/plate_2.gcode': strToU8(GCODE_HEADER + 'G90\nM83\n;LAYER_CHANGE\nG1 Z0.2\nG1 X0 Y0\nG1 X5 Y0 E1\n'),
  })
}

/** A project 3MF with a cube in its build. */
export function projectCube3mf(transform?: string): Uint8Array {
  return zipSync({ '3D/3dmodel.model': strToU8(cubeModelXml(transform)) })
}

/** A `.gcode.3mf` that kept its mesh but has no plate G-code. */
export function meshOnlyGcode3mf(): Uint8Array {
  return zipSync({ '3D/3dmodel.model': strToU8(cubeModelXml()), 'Metadata/slice_info.config': strToU8('<config/>') })
}

/** A zip with neither a part nor a plate. */
export function emptyGcode3mf(): Uint8Array {
  return zipSync({ '3D/3dmodel.model': strToU8(EMPTY_BUILD) })
}

/** A binary STL with `count` copies of one triangle. */
export function binaryStl(count: number): Uint8Array {
  const bytes = new Uint8Array(84 + count * 50)
  const view = new DataView(bytes.buffer)
  view.setUint32(80, count, true)
  for (let i = 0; i < count; i++) {
    const o = 84 + i * 50 + 12
    ;[0, 0, 0, 10, 0, 0, 0, 10, 0].forEach((value, k) => view.setFloat32(o + k * 4, value, true))
  }
  return bytes
}

export function toBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.slice().buffer as ArrayBuffer
}
