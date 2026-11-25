// @vitest-environment node
/** What the viewer says a sliced file was made for (spec 004, FR-021). */
import { describe, expect, it } from 'vitest'
import { mismatches } from './notices'

const PRINTER = { name: 'Workshop P1S', model: 'P1S', nozzle_diameter_mm: 0.4 }

describe('mismatches', () => {
  it('names each material once when several lines share it (walkthrough)', () => {
    expect(mismatches({ filamentType: 'PETG' }, PRINTER, ['PLA', 'PLA'])).toEqual([
      'Sliced for PETG; the bill of materials uses PLA.',
    ])
  })

  it('says nothing when the file matches the plan', () => {
    expect(mismatches({ printerModel: 'Bambu Lab P1S', filamentType: 'PLA' }, PRINTER, ['PLA'])).toEqual([])
  })

  it('names the printer the file was sliced for', () => {
    expect(mismatches({ printerModel: 'Bambu Lab A1' }, PRINTER, [])).toEqual([
      'Sliced for Bambu Lab A1; the planned printer is Workshop P1S.',
    ])
  })
})
