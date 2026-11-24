/**
 * E2E Tests: Consumables - Field Validation
 *
 * Comprehensive tests verifying that each consumable form field correctly
 * saves to the database and is displayed properly in the UI.
 *
 * Consumable Fields Tested:
 * - Required: sku, name
 * - Optional text: description, preferred_supplier, supplier_sku, supplier_url
 * - Numeric: current_cost_per_unit, quantity_on_hand, reorder_point, reorder_quantity, typical_lead_days
 * - Boolean: is_active
 * - Select: category, unit_of_measure
 */

import { test, expect, Page, Locator } from '@playwright/test'
import { apiAs, isBackendAvailable, registerAndLogin, uniqueSuffix } from '../../helpers'

// Each test signs up a fresh tenant first; leave room for a busy shared backend.
test.describe.configure({ timeout: 90_000 })

interface Consumable {
  sku: string
  name: string
  description: string | null
  category: string | null
  unit_of_measure: string
  current_cost_per_unit: string | number | null
  quantity_on_hand: number
  reorder_point: number | null
  reorder_quantity: number | null
  preferred_supplier: string | null
  supplier_sku: string | null
  supplier_url: string | null
  typical_lead_days: number | null
  is_active: boolean
}

function generateCompleteConsumableData() {
  const suffix = uniqueSuffix()
  return {
    sku: `COM-TEST-${suffix}`.toUpperCase(),
    name: `Test Magnet ${suffix}`,
    description: 'Test consumable with all fields populated',
    category: 'hardware',
    unit_of_measure: 'each',
    current_cost_per_unit: 0.05,
    quantity_on_hand: 500,
    reorder_point: 100,
    reorder_quantity: 200,
    preferred_supplier: 'Amazon',
    supplier_sku: 'B09XYZ123',
    supplier_url: 'https://amazon.co.uk/dp/B09XYZ123',
    typical_lead_days: 3,
  }
}

/**
 * Open the dialog from the page header's "Add Consumable" button (an empty
 * list shows a second one) and wait for the auto-generated SKU.
 */
async function openAddConsumableDialog(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Add Consumable' }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Add New Consumable' })).toBeVisible()
  await expect(dialog.locator('#sku')).not.toHaveValue('', { timeout: 30000 })
  return dialog
}

/** Replace the auto-generated SKU with a known one. */
async function fillUniqueSku(dialog: Locator, sku?: string): Promise<string> {
  const uniqueSku = sku || `COM-TEST-${uniqueSuffix()}`.toUpperCase()
  await dialog.locator('#sku').fill(uniqueSku)
  return uniqueSku
}

async function pickOption(page: Page, trigger: Locator, option: string): Promise<void> {
  await trigger.click()
  await page.getByRole('option', { name: option, exact: true }).click()
  await expect(trigger).toHaveText(option)
}

/** Submit, check the new row in the list, and return the saved record. */
async function submitAndVerifyConsumable(page: Page, sku: string, name: string): Promise<Consumable> {
  await page.getByRole('dialog').getByRole('button', { name: 'Create Consumable' }).click()
  await expect(page.getByRole('dialog')).toBeHidden({ timeout: 30000 })

  const row = page.getByRole('row', { name: new RegExp(sku) })
  await expect(row.getByRole('cell', { name: sku, exact: true })).toBeVisible({ timeout: 10000 })
  await expect(row.getByText(name, { exact: true })).toBeVisible()

  return getConsumable(page, sku)
}

async function getConsumable(page: Page, sku: string): Promise<Consumable> {
  const api = await apiAs(page)
  const data = await api.get<{ consumables: Consumable[] }>(
    `/api/v1/consumables/types?search=${encodeURIComponent(sku)}`
  )
  const created = data.consumables.find((c) => c.sku === sku)
  expect(created, `consumable ${sku} saved`).toBeTruthy()
  return created!
}

test.describe('Consumable Field Validation - Required Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/consumables')
  })

  test('should display consumables page with add button', async ({ page }) => {
    await expect(page.getByRole('heading', { level: 1, name: 'Consumables Inventory' })).toBeVisible()
    // Header button, plus the empty state's own for a new tenant
    await expect(page.getByRole('button', { name: 'Add Consumable' })).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Add Consumable' }).first()).toBeVisible()
    await expect(page.getByText('No consumables found')).toBeVisible()
  })

  test('should open add consumable dialog', async ({ page }) => {
    const dialog = await openAddConsumableDialog(page)
    await expect(dialog.getByLabel(/^SKU/)).toBeVisible()
    await expect(dialog.getByLabel(/^Name/)).toBeVisible()

    // The empty state's button opens the same dialog
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await page.getByRole('button', { name: 'Add Consumable' }).last().click()
    await expect(dialog.getByRole('heading', { name: 'Add New Consumable' })).toBeVisible()
  })

  test('should save sku correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    // Clear auto-generated SKU and fill with test SKU
    await fillUniqueSku(dialog, testData.sku)
    await dialog.locator('#name').fill(testData.name)

    const saved = await submitAndVerifyConsumable(page, testData.sku, testData.name)
    expect(saved.sku).toBe(testData.sku)
  })

  test('should save auto-generated sku', async ({ page }) => {
    const name = `Auto SKU ${uniqueSuffix()}`

    const dialog = await openAddConsumableDialog(page)
    const generated = await dialog.locator('#sku').inputValue()
    expect(generated).toMatch(/^COM-/)
    await dialog.locator('#name').fill(name)

    const saved = await submitAndVerifyConsumable(page, generated, name)
    expect(saved.name).toBe(name)
  })

  test('should save name correctly', async ({ page }) => {
    const uniqueName = `Unique Consumable ${uniqueSuffix()}`

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(uniqueName)

    const saved = await submitAndVerifyConsumable(page, sku, uniqueName)
    expect(saved.name).toBe(uniqueName)
  })
})

test.describe('Consumable Field Validation - Optional Text Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/consumables')
  })

  test('should save description correctly', async ({ page }) => {
    const uniqueName = `Description Test ${uniqueSuffix()}`
    const description = 'Detailed description with special chars: @#$%^&*()'

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(uniqueName)
    await dialog.locator('#description').fill(description)

    const saved = await submitAndVerifyConsumable(page, sku, uniqueName)
    expect(saved.description).toBe(description)
  })

  test('should save preferred_supplier correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#preferred_supplier').fill('Amazon UK')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.preferred_supplier).toBe('Amazon UK')
  })

  test('should save supplier_sku correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#supplier_sku').fill('B09SUPPLIER123')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.supplier_sku).toBe('B09SUPPLIER123')
  })

  test('should save supplier_url correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#supplier_url').fill('https://amazon.co.uk/dp/B09TEST123')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.supplier_url).toBe('https://amazon.co.uk/dp/B09TEST123')
  })
})

test.describe('Consumable Field Validation - Numeric Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/consumables')
  })

  test('should save current_cost_per_unit correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#current_cost_per_unit').fill('0.0575')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(parseFloat(String(saved.current_cost_per_unit))).toBe(0.0575)
  })

  test('should save quantity_on_hand correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#quantity_on_hand').fill('500')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.quantity_on_hand).toBe(500)
  })

  test('should save reorder_point correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#reorder_point').fill('100')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.reorder_point).toBe(100)
  })

  test('should save reorder_quantity correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#reorder_quantity').fill('200')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.reorder_quantity).toBe(200)
  })

  test('should save typical_lead_days correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#typical_lead_days').fill('5')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.typical_lead_days).toBe(5)
  })
})

test.describe('Consumable Field Validation - Select Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/consumables')
  })

  test('should save category selection correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await pickOption(page, dialog.locator('#category'), 'Magnets')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.category).toBe('magnets')
  })

  test('should save unit_of_measure selection correctly', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)
    await pickOption(page, dialog.locator('#unit_of_measure'), 'pack')

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.unit_of_measure).toBe('pack')
  })

  test('should verify all category options exist', async ({ page }) => {
    const dialog = await openAddConsumableDialog(page)

    await dialog.locator('#category').click()
    for (const category of ['Magnets', 'Inserts', 'Hardware', 'Finishing', 'Packaging', 'Adhesives', 'Other']) {
      await expect(page.getByRole('option', { name: category, exact: true })).toBeVisible()
    }
  })
})

test.describe('Consumable Field Validation - Boolean Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/consumables')
  })

  test('should save is_active toggle correctly (enabled by default)', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)

    // is_active should be checked by default
    await expect(dialog.locator('#is_active')).toBeChecked()

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.is_active).toBe(true)
  })

  test('should save is_active toggle when disabled', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    const sku = await fillUniqueSku(dialog)
    await dialog.locator('#name').fill(testData.name)

    const activeSwitch = dialog.locator('#is_active')
    await activeSwitch.click()
    await expect(activeSwitch).not.toBeChecked()

    const saved = await submitAndVerifyConsumable(page, sku, testData.name)
    expect(saved.is_active).toBe(false)
  })
})

test.describe('Consumable Field Validation - Complete Form', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/consumables')
  })

  test('should create consumable with ALL fields populated', async ({ page }) => {
    const testData = generateCompleteConsumableData()

    const dialog = await openAddConsumableDialog(page)
    await fillUniqueSku(dialog, testData.sku)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#description').fill(testData.description)
    await pickOption(page, dialog.locator('#category'), 'Hardware')
    await pickOption(page, dialog.locator('#unit_of_measure'), 'box')
    await dialog.locator('#current_cost_per_unit').fill(testData.current_cost_per_unit.toString())
    await dialog.locator('#quantity_on_hand').fill(testData.quantity_on_hand.toString())
    await dialog.locator('#reorder_point').fill(testData.reorder_point.toString())
    await dialog.locator('#reorder_quantity').fill(testData.reorder_quantity.toString())
    await dialog.locator('#preferred_supplier').fill(testData.preferred_supplier)
    await dialog.locator('#supplier_sku').fill(testData.supplier_sku)
    await dialog.locator('#supplier_url').fill(testData.supplier_url)
    await dialog.locator('#typical_lead_days').fill(testData.typical_lead_days.toString())

    const saved = await submitAndVerifyConsumable(page, testData.sku, testData.name)
    expect(saved).toMatchObject({
      sku: testData.sku,
      name: testData.name,
      description: testData.description,
      category: 'hardware',
      unit_of_measure: 'box',
      quantity_on_hand: testData.quantity_on_hand,
      reorder_point: testData.reorder_point,
      reorder_quantity: testData.reorder_quantity,
      preferred_supplier: testData.preferred_supplier,
      supplier_sku: testData.supplier_sku,
      supplier_url: testData.supplier_url,
      typical_lead_days: testData.typical_lead_days,
      is_active: true,
    })
    expect(parseFloat(String(saved.current_cost_per_unit))).toBe(testData.current_cost_per_unit)
  })

  test('should verify created consumable data via API', async ({ page }) => {
    const testData = generateCompleteConsumableData()
    const uniqueSku = `API-COM-${uniqueSuffix()}`.toUpperCase()

    const dialog = await openAddConsumableDialog(page)
    await fillUniqueSku(dialog, uniqueSku)
    await dialog.locator('#name').fill(testData.name)
    await dialog.locator('#quantity_on_hand').fill('250')
    await dialog.locator('#current_cost_per_unit').fill('0.05')

    await submitAndVerifyConsumable(page, uniqueSku, testData.name)

    // Read back through the plain list endpoint, unfiltered
    const api = await apiAs(page)
    const data = await api.get<{ consumables: Consumable[] }>('/api/v1/consumables/types')
    const created = data.consumables.find((c) => c.sku === uniqueSku)
    expect(created).toBeTruthy()
    expect(created!.name).toBe(testData.name)
    expect(created!.quantity_on_hand).toBe(250)
    expect(parseFloat(String(created!.current_cost_per_unit))).toBe(0.05)
  })
})

test.describe('Consumable Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
  })

  test('should navigate to consumables page from dashboard', async ({ page }) => {
    await page.goto('/dashboard')

    await page.getByRole('navigation').getByRole('link', { name: 'Consumables', exact: true }).click()
    await expect(page).toHaveURL(/\/consumables/)
    await expect(page.getByRole('heading', { level: 1, name: 'Consumables Inventory' })).toBeVisible()
  })

  test('should require authentication for consumables page', async ({ page }) => {
    // Logout and wait for redirect to login page
    await page.goto('/logout')
    await page.waitForURL(/\/login/, { timeout: 10000 })

    // Now try to access protected route
    await page.goto('/consumables')
    await expect(page).toHaveURL(/\/login/)
  })
})
