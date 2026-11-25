/**
 * E2E Tests: Printers - Field Validation
 *
 * Comprehensive tests verifying that each printer form field correctly
 * saves to the database and is displayed properly in the UI.
 *
 * Printer Fields Tested:
 * - Required: name
 * - Optional text: manufacturer, model, serial_number, notes
 * - Numeric: bed_size_x/y/z_mm, nozzle_diameter_mm, default_bed_temp, default_nozzle_temp
 * - Boolean: is_active
 */

import { type Page } from '@playwright/test'
import { test, expect } from '../../fixtures'
import { apiAs, isBackendAvailable, openDashboard } from '../../helpers'

function generateCompletePrinterData() {
  const timestamp = Date.now()
  return {
    name: `Test Printer ${timestamp}`,
    manufacturer: 'Bambu Lab',
    // The model is picked from the known-model list (stored as its key)
    model: 'Bambu X1 Carbon',
    modelKey: 'bambu_x1c',
    serial_number: `SN-${timestamp}`,
    bed_size_x_mm: 256,
    bed_size_y_mm: 256,
    bed_size_z_mm: 256,
    nozzle_diameter_mm: 0.4,
    default_bed_temp: 60,
    default_nozzle_temp: 220,
    notes: 'Test printer with all fields populated',
  }
}

// Pick a model from the known-model select
async function selectModel(page: Page, displayName: string): Promise<void> {
  await page.locator('#model').click()
  await page.getByRole('option', { name: displayName, exact: true }).click()
}

// The saved printer, read back through the API
async function savedPrinter(page: Page, name: string) {
  const api = await apiAs(page)
  const data = await api.get('/api/v1/printers')
  return data.printers.find((p: { name: string }) => p.name === name)
}

// Helper to open dialog and wait for it to be ready
async function openAddPrinterDialog(page: Page): Promise<void> {
  await page.getByRole('button', { name: /add printer/i }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
}

// Helper to fill required printer fields
async function fillRequiredPrinterFields(page: Page, name: string): Promise<void> {
  await page.locator('#name').fill(name)
}

// Helper to submit form and verify creation
async function submitAndVerifyPrinter(page: Page, verifyText: string): Promise<void> {
  await page.getByRole('button', { name: /add printer$/i }).click()
  await expect(page.getByRole('dialog')).toBeHidden({ timeout: 30000 })
  // The name cell (exact: the row's cost button is labelled "Machine cost for <name>")
  await expect(page.getByRole('cell', { name: verifyText, exact: true })).toBeVisible({
    timeout: 10000,
  })
}

test.describe('Printer Field Validation - Required Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/printers')
  })

  test('should display printers page with add button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /add printer/i }).first()).toBeVisible()
  })

  test('should open add printer dialog', async ({ page }) => {
    await openAddPrinterDialog(page)
    await expect(page.getByRole('heading', { name: 'Add Printer' })).toBeVisible()
  })

  test('should save name correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await submitAndVerifyPrinter(page, testData.name)
  })
})

test.describe('Printer Field Validation - Optional Text Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/printers')
  })

  test('should save manufacturer correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await page.locator('#manufacturer').fill('Prusa Research')
    await submitAndVerifyPrinter(page, testData.name)
    expect((await savedPrinter(page, testData.name)).manufacturer).toBe('Prusa Research')
  })

  test('should save model correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await selectModel(page, 'Bambu X1 Carbon')
    // Picking a known model fills in its manufacturer
    await expect(page.locator('#manufacturer')).toHaveValue('Bambu Lab')
    await submitAndVerifyPrinter(page, testData.name)
    expect((await savedPrinter(page, testData.name)).model).toBe('bambu_x1c')
  })

  // Regression: .specify/bugs/printer-serial-dropped
  test('should save serial_number correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await page.locator('#serial_number').fill('SN-TEST-12345')
    await submitAndVerifyPrinter(page, testData.name)
    expect((await savedPrinter(page, testData.name)).serial_number).toBe('SN-TEST-12345')
  })

  test('should save notes correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)

    await page.locator('#notes').fill('Test notes with special chars: @#$%')
    await submitAndVerifyPrinter(page, testData.name)
    expect((await savedPrinter(page, testData.name)).notes).toBe('Test notes with special chars: @#$%')
  })
})

test.describe('Printer Field Validation - Numeric Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/printers')
  })

  test('should save bed dimensions correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await page.locator('#bed_size_x_mm').fill('300')
    await page.locator('#bed_size_y_mm').fill('300')
    await page.locator('#bed_size_z_mm').fill('400')
    await submitAndVerifyPrinter(page, testData.name)
    const saved = await savedPrinter(page, testData.name)
    expect([saved.bed_size_x_mm, saved.bed_size_y_mm, saved.bed_size_z_mm]).toEqual([300, 300, 400])
  })

  test('should save nozzle_diameter_mm correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await page.locator('#nozzle_diameter_mm').fill('0.6')
    await submitAndVerifyPrinter(page, testData.name)
    expect(Number((await savedPrinter(page, testData.name)).nozzle_diameter_mm)).toBe(0.6)
  })

  test('should save temperature defaults correctly', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)
    await page.locator('#default_bed_temp').fill('65')
    await page.locator('#default_nozzle_temp').fill('215')
    await submitAndVerifyPrinter(page, testData.name)
    const saved = await savedPrinter(page, testData.name)
    expect([saved.default_bed_temp, saved.default_nozzle_temp]).toEqual([65, 215])
  })
})

test.describe('Printer Field Validation - Boolean Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/printers')
  })

  test('should save is_active toggle correctly (enabled by default)', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)

    // is_active should be checked by default
    await expect(page.locator('#is_active')).toBeChecked()
    await submitAndVerifyPrinter(page, testData.name)
    expect((await savedPrinter(page, testData.name)).is_active).toBe(true)
  })

  test('should save is_active toggle when disabled', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)

    // Toggle off is_active
    await page.locator('#is_active').click()
    await expect(page.locator('#is_active')).not.toBeChecked()
    await submitAndVerifyPrinter(page, testData.name)
    expect((await savedPrinter(page, testData.name)).is_active).toBe(false)
  })
})

test.describe('Printer Field Validation - Complete Form', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/printers')
  })

  test('should create printer with ALL fields populated', async ({ page }) => {
    const testData = generateCompletePrinterData()

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, testData.name)

    // Optional text fields
    await selectModel(page, testData.model)
    await page.locator('#manufacturer').fill(testData.manufacturer)
    await page.locator('#serial_number').fill(testData.serial_number)

    // Build volume
    await page.locator('#bed_size_x_mm').fill(testData.bed_size_x_mm.toString())
    await page.locator('#bed_size_y_mm').fill(testData.bed_size_y_mm.toString())
    await page.locator('#bed_size_z_mm').fill(testData.bed_size_z_mm.toString())

    // Print settings
    await page.locator('#nozzle_diameter_mm').fill(testData.nozzle_diameter_mm.toString())
    await page.locator('#default_bed_temp').fill(testData.default_bed_temp.toString())
    await page.locator('#default_nozzle_temp').fill(testData.default_nozzle_temp.toString())

    // Notes
    await page.locator('#notes').fill(testData.notes)

    await submitAndVerifyPrinter(page, testData.name)
    const saved = await savedPrinter(page, testData.name)
    expect(saved).toMatchObject({
      manufacturer: testData.manufacturer,
      model: testData.modelKey,
      bed_size_x_mm: testData.bed_size_x_mm,
      default_bed_temp: testData.default_bed_temp,
      default_nozzle_temp: testData.default_nozzle_temp,
      notes: testData.notes,
    })
  })

  test('should verify created printer data via API', async ({ page }) => {
    const uniqueName = `API Printer ${Date.now()}`

    await openAddPrinterDialog(page)
    await fillRequiredPrinterFields(page, uniqueName)
    await page.locator('#manufacturer').fill('Test Manufacturer')
    await page.locator('#bed_size_x_mm').fill('250')

    await submitAndVerifyPrinter(page, uniqueName)

    // Verify via API
    const created = await savedPrinter(page, uniqueName)
    expect(created).toBeTruthy()
    expect(created.manufacturer).toBe('Test Manufacturer')
    expect(created.bed_size_x_mm).toBe(250)
  })
})

test.describe('Printer Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await openDashboard(page)
  })

  test('should navigate to printers page', async ({ page }) => {
    await page.goto('/printers')
    await expect(page).toHaveURL(/\/printers/)
  })

  test('should require authentication for printers page', async ({ page }) => {
    // Logout and wait for redirect to login page
    await page.goto('/logout')
    await page.waitForURL(/\/login/, { timeout: 10000 })

    // Now try to access protected route
    await page.goto('/printers')
    await expect(page).toHaveURL(/\/login/)
  })
})
