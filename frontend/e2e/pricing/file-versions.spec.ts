/**
 * Model file versions, end to end (spec 004, T034).
 *
 * Upload a part as version 1, a sliced plate as a new version 2, make version
 * 2 active applying only its print time, and see the print time recorded as
 * measured. Runs with the pricing journeys (CI `--project=pricing`) as the
 * seeded owner, on a model it creates, so the seeded figures stay untouched.
 */

import { expect, test } from '@playwright/test'

import { OWNER_STATE } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

/** A 20 mm cube as a binary STL. */
function cubeStl(): Buffer {
  const v = [
    [0, 0, 0], [20, 0, 0], [20, 20, 0], [0, 20, 0],
    [0, 0, 20], [20, 0, 20], [20, 20, 20], [0, 20, 20],
  ]
  const t = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
  ]
  const buf = Buffer.alloc(84 + t.length * 50)
  buf.writeUInt32LE(t.length, 80)
  t.forEach((tri, i) => {
    tri.forEach((vi, k) => {
      v[vi].forEach((c, j) => buf.writeFloatLE(c, 84 + i * 50 + 12 + (k * 3 + j) * 4))
    })
  })
  return buf
}

const SLICED_GCODE = `; HEADER_BLOCK_START
; BambuStudio 02.00.00.00
; total estimated time: 1h 58m 0s
; HEADER_BLOCK_END
; printer_model = Bambu Lab A1
; filament_type = PLA
; nozzle_diameter = 0.4
G90
M83
;LAYER_CHANGE
G1 Z0.2
G1 X10 Y10
G1 X30 Y10 E1
`

test('a new version is made active with only the figures chosen', async ({ page }) => {
  const name = `E2E Versions ${Date.now()}`
  await page.goto('/models/new')
  await page.getByLabel('Name').fill(name)
  await page.getByRole('button', { name: 'Create Model' }).click()
  await page.waitForURL(/\/models\/[0-9a-f-]+$/)
  await page.goto(`${page.url()}/edit`)

  const upload = page.getByLabel('Choose files to upload')

  // Version 1: the part.
  await upload.setInputFiles({ name: 'part_v1.stl', mimeType: 'model/stl', buffer: cubeStl() })
  const v1 = page.getByRole('listitem', { name: 'Version 1' })
  await expect(v1.getByText('part_v1.stl')).toBeVisible()
  await expect(v1.getByText('Active')).toBeVisible()

  // Version 2: a sliced plate, uploaded into a new version.
  await page.getByRole('combobox', { name: 'Add to version' }).first().click()
  await page.getByRole('option', { name: 'New version…' }).click()
  await page.getByLabel('What changed').first().fill('thicker walls')
  await upload.setInputFiles({
    name: 'plate_v2.gcode',
    mimeType: 'text/plain',
    buffer: Buffer.from(SLICED_GCODE),
  })
  await expect(page.getByText(/Version 2 was created/)).toBeVisible()

  // Make it active, applying only the print time.
  await page.getByRole('button', { name: 'Make active' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Make version 2 active' })
  const printTime = dialog.getByRole('checkbox', { name: 'Plate print time' })
  await expect(printTime).toBeChecked()
  for (const other of ['Items per plate', 'Filament weight', 'Dimensions']) {
    const box = dialog.getByRole('checkbox', { name: other })
    if ((await box.count()) > 0 && (await box.isChecked())) await box.click()
  }
  await dialog.getByRole('button', { name: 'Make active' }).click()
  await expect(dialog).toBeHidden()

  await expect(page.getByRole('listitem', { name: 'Version 2' }).getByText('Active')).toBeVisible()
  // The print time now says it was measured from the file.
  await expect(page.getByTestId('provenance-measured').first()).toBeVisible()
})
