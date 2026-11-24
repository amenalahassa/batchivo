/**
 * E2E Tests: Inventory - Spool Field Validation
 *
 * Verifies that each field of the Filament Library's "Add Filament" form
 * (mode "Batch of identical spools": one filament type + N spools) saves to
 * the database and shows in the UI.
 *
 * Tests cover:
 * - Required fields (brand, color, material type, weight per spool) and the
 *   auto-generated spool ID
 * - Optional text fields (finish, notes, pattern, color hex, spool type)
 * - Numeric fields (diameter, density, temps, number of spools)
 * - Boolean fields (translucent, glow)
 *
 * The form lives at /filaments (/inventory redirects there). Spool-level
 * fields the old "Add Spool" dialog had (storage location, purchase date and
 * price, empty spool weight, a hand-typed spool ID) are not part of it.
 */

import { test, expect, Page, Locator } from '@playwright/test'
import { apiAs, isBackendAvailable, registerAndLogin, uniqueSuffix } from '../../helpers'

// Each test signs up a fresh tenant first; leave room for a busy shared backend.
test.describe.configure({ timeout: 90_000 })

interface MaterialType {
  id: string
  code: string
  name: string
}

interface FilamentType {
  id: string
  brand: string
  color: string
  color_hex: string | null
  finish: string | null
  pattern: string | null
  spool_type: string | null
  diameter: number
  density: number | null
  extruder_temp: number | null
  bed_temp: number | null
  translucent: boolean
  glow: boolean
  notes: string | null
  material_type_code: string
  material_type_name: string
}

interface SheetSpool {
  id: string
  spool_id: string
  initial_weight: number
  current_weight: number
}

interface BulkCreateResult {
  filament_type_id: string
  spool_ids: string[]
}

function generateSpoolData() {
  const suffix = uniqueSuffix()
  return {
    brand: `TestBrand-${suffix}`,
    color: `Electric Blue ${suffix}`,
    color_hex: '#FF5733',
    finish: 'Matte',
    diameter: '2.85',
    density: '1.27',
    extruder_temp: '215',
    bed_temp: '60',
    pattern: 'Marble',
    spool_type: 'Cardboard',
    initial_weight: '1000',
    notes: 'Test spool with all fields populated for E2E validation',
  }
}

/** Open "Add Filament" and pick "Batch of identical spools". */
async function openBulkAddForm(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Add Filament' }).click()
  const dialog = page.getByRole('dialog')
  await expect(
    dialog.getByRole('heading', { name: 'How would you like to add filament?' })
  ).toBeVisible()
  await dialog.getByText('Batch of identical spools').click()
  await expect(dialog.getByRole('heading', { name: 'Add filament — batch' })).toBeVisible()
  return dialog
}

/** Pick a material type by its display name in the form's select. */
async function selectMaterial(page: Page, dialog: Locator, name: string): Promise<void> {
  await dialog.getByRole('combobox', { name: 'Material type' }).click()
  await page.getByRole('option', { name, exact: true }).click()
  await expect(dialog.getByRole('combobox', { name: 'Material type' })).toHaveText(name)
}

async function firstMaterial(page: Page): Promise<MaterialType> {
  const api = await apiAs(page)
  const materials = await api.get<MaterialType[]>('/api/v1/spools/material-types')
  expect(materials.length).toBeGreaterThan(0)
  return materials[0]
}

async function fillRequiredFields(
  page: Page,
  dialog: Locator,
  data: { brand: string; color: string }
): Promise<MaterialType> {
  await dialog.getByLabel('Brand').fill(data.brand)
  await dialog.getByLabel('Color', { exact: true }).fill(data.color)
  const material = await firstMaterial(page)
  await selectMaterial(page, dialog, material.name)
  return material
}

async function openMoreOptions(dialog: Locator): Promise<void> {
  await dialog.getByRole('button', { name: 'More options' }).click()
  await expect(dialog.getByLabel('Color hex')).toBeVisible()
}

/** Submit the form; returns what the backend created. */
async function submitBulkForm(page: Page, dialog: Locator): Promise<BulkCreateResult> {
  const created = page.waitForResponse(
    (r) => r.url().includes('/api/v1/filament-types/bulk-create') && r.request().method() === 'POST'
  )
  await dialog.getByRole('button', { name: 'Add spools' }).click()
  const response = await created
  expect(response.status()).toBe(201)
  await expect(dialog).toBeHidden({ timeout: 15000 })
  return (await response.json()) as BulkCreateResult
}

async function getFilamentType(page: Page, id: string): Promise<FilamentType> {
  const api = await apiAs(page)
  return api.get<FilamentType>(`/api/v1/filament-types/${id}`)
}

async function getSpools(page: Page, filamentTypeId: string): Promise<SheetSpool[]> {
  const api = await apiAs(page)
  return api.get<SheetSpool[]>(`/api/v1/filament-types/${filamentTypeId}/spools`)
}

/** The filament type's row in the (desktop) library table. */
function libraryRow(page: Page, brand: string): Locator {
  return page.getByRole('row', { name: new RegExp(brand) })
}

/** Click a library row to open its read-only spool sheet. */
async function openSpoolSheet(page: Page, brand: string): Promise<Locator> {
  await libraryRow(page, brand).click()
  const sheet = page.getByRole('dialog')
  await expect(sheet.getByRole('columnheader', { name: 'Spool ID' })).toBeVisible()
  return sheet
}

test.describe('Spool Field Validation - Required Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
    await expect(page.getByRole('heading', { level: 1, name: 'Filament Library' })).toBeVisible()
  })

  test('should generate and save spool_id correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    const created = await submitBulkForm(page, dialog)

    expect(created.spool_ids).toHaveLength(1)
    const [spoolId] = created.spool_ids
    expect(spoolId).toMatch(/^FIL-\d+$/)

    const spools = await getSpools(page, created.filament_type_id)
    expect(spools.map((s) => s.spool_id)).toEqual([spoolId])

    const sheet = await openSpoolSheet(page, testData.brand)
    await expect(sheet.getByRole('cell', { name: spoolId, exact: true })).toBeVisible()
  })

  test('should save brand correctly', async ({ page }) => {
    const testData = generateSpoolData()
    const uniqueBrand = `UniqueBrandTest-${uniqueSuffix()}`

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, { ...testData, brand: uniqueBrand })
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, uniqueBrand)).toBeVisible()
    expect((await getFilamentType(page, created.filament_type_id)).brand).toBe(uniqueBrand)
  })

  test('should save color correctly', async ({ page }) => {
    const testData = generateSpoolData()
    const uniqueColor = `UniqueColor-${uniqueSuffix()}`

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, { ...testData, color: uniqueColor })
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand).getByRole('cell', { name: uniqueColor, exact: true })).toBeVisible()
    expect((await getFilamentType(page, created.filament_type_id)).color).toBe(uniqueColor)
  })

  test('should save initial_weight and current_weight correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await dialog.getByLabel('Weight per spool (g)').fill('750')
    const created = await submitBulkForm(page, dialog)

    // A new spool starts full: current weight = initial weight.
    const spools = await getSpools(page, created.filament_type_id)
    expect(spools).toHaveLength(1)
    expect(spools[0].initial_weight).toBe(750)
    expect(spools[0].current_weight).toBe(750)

    const sheet = await openSpoolSheet(page, testData.brand)
    await expect(sheet.getByRole('cell', { name: '750g / 750g' })).toBeVisible()
  })
})

test.describe('Spool Field Validation - Optional Text Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
  })

  test('should save finish field correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await dialog.getByLabel('Finish').fill('Glossy Metallic')
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand)).toBeVisible()
    expect((await getFilamentType(page, created.filament_type_id)).finish).toBe('Glossy Metallic')
  })

  test('should save pattern field correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Pattern').fill('Speckled Granite')
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand)).toBeVisible()
    expect((await getFilamentType(page, created.filament_type_id)).pattern).toBe('Speckled Granite')
  })

  test('should save notes correctly', async ({ page }) => {
    const testData = generateSpoolData()
    const notes = 'This is a test note with special chars: !@#$%^&*()'

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await dialog.getByLabel('Notes').fill(notes)
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand)).toBeVisible()
    expect((await getFilamentType(page, created.filament_type_id)).notes).toBe(notes)
  })

  test('should save color_hex correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Color hex').fill('#FF5733')
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand)).toBeVisible()
    // Stored without the '#'.
    expect((await getFilamentType(page, created.filament_type_id)).color_hex).toBe('FF5733')
  })

  test('should save spool_type correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Spool type').fill('Cardboard')
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand)).toBeVisible()
    expect((await getFilamentType(page, created.filament_type_id)).spool_type).toBe('Cardboard')
  })
})

test.describe('Spool Field Validation - Numeric Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
  })

  test('should save temperature fields correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Extruder temp (°C)').fill('215')
    await dialog.getByLabel('Bed temp (°C)').fill('60')
    const created = await submitBulkForm(page, dialog)

    const ft = await getFilamentType(page, created.filament_type_id)
    expect(ft.extruder_temp).toBe(215)
    expect(ft.bed_temp).toBe(60)
  })

  test('should save density correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Density (g/cm³)').fill('1.27')
    const created = await submitBulkForm(page, dialog)

    expect((await getFilamentType(page, created.filament_type_id)).density).toBe(1.27)
  })

  test('should save diameter correctly (1.75mm)', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Diameter (mm)').fill('1.75')
    const created = await submitBulkForm(page, dialog)

    expect((await getFilamentType(page, created.filament_type_id)).diameter).toBe(1.75)
  })

  test('should save diameter correctly (2.85mm)', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Diameter (mm)').fill('2.85')
    const created = await submitBulkForm(page, dialog)

    expect((await getFilamentType(page, created.filament_type_id)).diameter).toBe(2.85)
  })

  test('should save quantity fields correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await dialog.getByRole('button', { name: 'Increase quantity' }).click()
    await dialog.getByRole('button', { name: 'Increase quantity' }).click()
    const created = await submitBulkForm(page, dialog)

    expect(created.spool_ids).toHaveLength(3)
    expect(await getSpools(page, created.filament_type_id)).toHaveLength(3)

    await expect(libraryRow(page, testData.brand).getByText('3 spools')).toBeVisible()
    const sheet = await openSpoolSheet(page, testData.brand)
    for (const spoolId of created.spool_ids) {
      await expect(sheet.getByRole('cell', { name: spoolId, exact: true })).toBeVisible()
    }
  })
})

test.describe('Spool Field Validation - Boolean Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
  })

  test('should save translucent toggle correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Translucent').check()
    const created = await submitBulkForm(page, dialog)

    const ft = await getFilamentType(page, created.filament_type_id)
    expect(ft.translucent).toBe(true)
    expect(ft.glow).toBe(false)
  })

  test('should save glow toggle correctly', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Glow in the dark').check()
    const created = await submitBulkForm(page, dialog)

    const ft = await getFilamentType(page, created.filament_type_id)
    expect(ft.glow).toBe(true)
    expect(ft.translucent).toBe(false)
  })

  test('should save both boolean fields when enabled', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await openMoreOptions(dialog)
    await dialog.getByLabel('Translucent').check()
    await dialog.getByLabel('Glow in the dark').check()
    const created = await submitBulkForm(page, dialog)

    const ft = await getFilamentType(page, created.filament_type_id)
    expect(ft.translucent).toBe(true)
    expect(ft.glow).toBe(true)
  })
})

test.describe('Spool Field Validation - Select Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
  })

  test('should save different material types correctly', async ({ page }) => {
    const testData = generateSpoolData()
    const api = await apiAs(page)
    const materials = await api.get<MaterialType[]>('/api/v1/spools/material-types')
    expect(materials.length).toBeGreaterThan(1)

    const dialog = await openBulkAddForm(page)
    await dialog.getByLabel('Brand').fill(testData.brand)
    await dialog.getByLabel('Color', { exact: true }).fill(testData.color)

    // Every material type is offered.
    await dialog.getByRole('combobox', { name: 'Material type' }).click()
    await expect(page.getByRole('option')).toHaveCount(materials.length)
    await page.keyboard.press('Escape')

    // Pick one that is not the first (default-looking) option.
    const material = materials[materials.length - 1]
    await selectMaterial(page, dialog, material.name)
    const created = await submitBulkForm(page, dialog)

    expect((await getFilamentType(page, created.filament_type_id)).material_type_code).toBe(
      material.code
    )
    await expect(
      libraryRow(page, testData.brand).getByRole('cell', { name: material.name, exact: true })
    ).toBeVisible()
  })
})

test.describe('Spool Field Validation - Complete Form', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
  })

  test('should save spool with ALL fields populated', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    const material = await fillRequiredFields(page, dialog, testData)
    await dialog.getByLabel('Finish').fill(testData.finish)
    await dialog.getByLabel('Notes').fill(testData.notes)

    await openMoreOptions(dialog)
    await dialog.getByLabel('Color hex').fill(testData.color_hex)
    await dialog.getByLabel('Diameter (mm)').fill(testData.diameter)
    await dialog.getByLabel('Extruder temp (°C)').fill(testData.extruder_temp)
    await dialog.getByLabel('Bed temp (°C)').fill(testData.bed_temp)
    await dialog.getByLabel('Density (g/cm³)').fill(testData.density)
    await dialog.getByLabel('Pattern').fill(testData.pattern)
    await dialog.getByLabel('Spool type').fill(testData.spool_type)
    await dialog.getByLabel('Translucent').check()
    await dialog.getByLabel('Glow in the dark').check()

    await dialog.getByLabel('Weight per spool (g)').fill(testData.initial_weight)
    await dialog.getByRole('button', { name: 'Increase quantity' }).click()

    const created = await submitBulkForm(page, dialog)

    // UI: the library row
    const row = libraryRow(page, testData.brand)
    await expect(row.getByRole('cell', { name: testData.color, exact: true })).toBeVisible()
    await expect(row.getByRole('cell', { name: material.name, exact: true })).toBeVisible()
    await expect(row.getByText('2 spools')).toBeVisible()

    // Database: every field
    const ft = await getFilamentType(page, created.filament_type_id)
    expect(ft).toMatchObject({
      brand: testData.brand,
      color: testData.color,
      color_hex: 'FF5733',
      finish: testData.finish,
      notes: testData.notes,
      diameter: 2.85,
      extruder_temp: 215,
      bed_temp: 60,
      density: 1.27,
      pattern: testData.pattern,
      spool_type: testData.spool_type,
      translucent: true,
      glow: true,
      material_type_code: material.code,
    })
    const spools = await getSpools(page, created.filament_type_id)
    expect(spools).toHaveLength(2)
    for (const spool of spools) {
      expect(spool.initial_weight).toBe(1000)
      expect(spool.current_weight).toBe(1000)
    }
  })

  test('should verify created spool data via API', async ({ page }) => {
    const testData = generateSpoolData()

    const dialog = await openBulkAddForm(page)
    await fillRequiredFields(page, dialog, testData)
    await dialog.getByLabel('Finish').fill('Silk')
    await dialog.getByLabel('Notes').fill('Test Location')
    await dialog.getByLabel('Weight per spool (g)').fill('750')
    const created = await submitBulkForm(page, dialog)

    await expect(libraryRow(page, testData.brand)).toBeVisible()

    // The spool, read back through the spools API with its filament type.
    const api = await apiAs(page)
    const data = await api.get<{
      spools: Array<{
        spool_id: string
        initial_weight: number | string
        current_weight: number | string
        filament_type: FilamentType | null
      }>
    }>('/api/v1/spools')
    const createdSpool = data.spools.find((s) => s.spool_id === created.spool_ids[0])
    expect(createdSpool).toBeTruthy()
    expect(parseFloat(String(createdSpool!.initial_weight))).toBe(750)
    expect(parseFloat(String(createdSpool!.current_weight))).toBe(750)
    expect(createdSpool!.filament_type).toMatchObject({
      id: created.filament_type_id,
      brand: testData.brand,
      color: testData.color,
      finish: 'Silk',
      notes: 'Test Location',
    })
  })
})
