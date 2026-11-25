/**
 * E2E Tests: Models - Field Validation
 *
 * Comprehensive tests verifying that each model form field correctly
 * saves to the database and is displayed properly in the UI.
 *
 * Model Fields Tested:
 * - Required: sku, name
 * - Optional text: description
 * - Selects: category, designer, source, machine
 * - Numeric: labor_hours, overhead_percentage, print_time_hours/minutes, prints_per_plate, units_in_stock
 * - Boolean: is_active
 */

import { type Page } from '@playwright/test'
import { test, expect } from '../../fixtures'
import { apiAs, isBackendAvailable, openDashboard } from '../../helpers'

const MODEL_DETAIL_URL = /\/models\/[0-9a-f-]{36}$/

function generateCompleteModelData() {
  const timestamp = Date.now()
  return {
    sku: `MOD-TEST-${timestamp}`,
    name: `Test Dragon Model ${timestamp}`,
    description: 'A detailed dragon model with articulated wings',
    labor_hours: '0.5',
    overhead_percentage: '10',
    designer: 'PrintyJay',
    source: 'Patreon',
    print_time_hours: '4',
    print_time_minutes: '30',
    prints_per_plate: '2',
    machine: 'Bambulabs A1 Mini',
    units_in_stock: '5',
  }
}

// Wait for the create form, including its auto-generated SKU: submitting
// before the SKU arrives fails validation ("SKU is required").
async function waitForModelForm(page: Page): Promise<void> {
  await expect(page.locator('input[name="name"]')).toBeVisible({ timeout: 10000 })
  await expect(page.locator('input[name="sku"]')).toHaveValue(/^MOD-/, { timeout: 10000 })
}

async function fillRequiredModelFields(page: Page, name: string, sku?: string): Promise<void> {
  if (sku) {
    await page.locator('input[name="sku"]').fill(sku)
  }
  await page.locator('input[name="name"]').fill(name)
}

// Pick an option in a labelled Radix select.
async function selectOption(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole('combobox', { name: label }).click()
  await page.getByRole('option', { name: option, exact: true }).click()
}

// Submit the create form, land on the new model's page, and return its id.
async function submitModel(page: Page): Promise<string> {
  await page.getByRole('button', { name: /create model/i }).click()
  await page.waitForURL(MODEL_DETAIL_URL, { timeout: 30000 })
  return page.url().split('/').pop()!
}

async function submitAndVerifyModel(page: Page, verifyText: string): Promise<string> {
  const modelId = await submitModel(page)
  await expect(page.getByText(verifyText).first()).toBeVisible({ timeout: 10000 })
  return modelId
}

async function fetchModel(page: Page, modelId: string) {
  return (await apiAs(page)).get(`/api/v1/models/${modelId}`)
}

test.describe('Model Field Validation - Required Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/models/new')
  })

  test('should display model creation form', async ({ page }) => {
    await waitForModelForm(page)
    await expect(page.getByRole('heading', { name: 'Create Model' })).toBeVisible()
    await expect(page.locator('input[name="sku"]')).toBeVisible()
    await expect(page.locator('input[name="name"]')).toBeVisible()
  })

  test('should save sku correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name, testData.sku)
    await submitAndVerifyModel(page, testData.sku)
  })

  test('should save name correctly', async ({ page }) => {
    const uniqueName = `Unique Model Name ${Date.now()}`

    await waitForModelForm(page)
    await fillRequiredModelFields(page, uniqueName)
    await submitAndVerifyModel(page, uniqueName)
  })

  test('should require name field', async ({ page }) => {
    await waitForModelForm(page)
    await page.locator('input[name="sku"]').fill('TEST-SKU')

    await page.getByRole('button', { name: /create model/i }).click()

    // Should show validation error
    await expect(page.getByText('Name is required')).toBeVisible()
    await expect(page).toHaveURL(/\/models\/new/)
  })
})

test.describe('Model Field Validation - Optional Text Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/models/new')
  })

  test('should save description correctly', async ({ page }) => {
    const uniqueName = `Model Desc Test ${Date.now()}`

    await waitForModelForm(page)
    await fillRequiredModelFields(page, uniqueName)
    await page.locator('textarea[name="description"]').fill('Detailed model description')

    await submitAndVerifyModel(page, uniqueName)
    await expect(page.getByText('Detailed model description')).toBeVisible()
  })

  test('should save category correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await selectOption(page, 'Category (Optional)', 'Parts')

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).category).toBe('parts')
  })

  test('should save designer correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    // The designer list comes from the Designers catalogue: seed one, then
    // reload the form so it lists it.
    await (await apiAs(page)).post('/api/v1/designers', { name: testData.designer })
    await page.reload()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await selectOption(page, 'Designer (Optional)', testData.designer)

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).designer).toBe(testData.designer)
  })

  // Regression: .specify/bugs/model-form-custom-value-lost (a typed designer
  // used to be reset to '' on blur and left out of the POST)
  test('should save a new designer typed in the form', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)

    await selectOption(page, 'Designer (Optional)', '+ Add new designer')
    await page.getByPlaceholder('Enter designer name').fill(testData.designer)

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).designer).toBe(testData.designer)
  })

  test('should save source correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await selectOption(page, 'Source (Optional)', testData.source)

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).source).toBe(testData.source)
  })

  test('should save machine correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await selectOption(page, 'Machine (Optional)', testData.machine)

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).machine).toBe(testData.machine)
  })
})

test.describe('Model Field Validation - Numeric Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/models/new')
  })

  test('should save labor_hours correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await page.locator('input[name="labor_hours"]').fill('0.75')

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect(Number((await fetchModel(page, modelId)).labor_hours)).toBe(0.75)
  })

  test('should save overhead_percentage correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await page.locator('input[name="overhead_percentage"]').fill('15')

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect(Number((await fetchModel(page, modelId)).overhead_percentage)).toBe(15)
  })

  test('should save print_time correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await page.locator('input[name="print_time_hours"]').fill('3')
    await page.locator('input[name="print_time_minutes"]').fill('45')

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).print_time_minutes).toBe(3 * 60 + 45)
  })

  test('should save prints_per_plate correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await page.locator('input[name="prints_per_plate"]').fill('4')

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).prints_per_plate).toBe(4)
  })

  test('should save units_in_stock correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)
    await page.locator('input[name="units_in_stock"]').fill('10')

    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).units_in_stock).toBe(10)
  })
})

test.describe('Model Field Validation - Boolean Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/models/new')
  })

  test('should save is_active toggle correctly', async ({ page }) => {
    const testData = generateCompleteModelData()

    await waitForModelForm(page)
    await fillRequiredModelFields(page, testData.name)

    // The create form has no status switch: a new model is active.
    const modelId = await submitAndVerifyModel(page, testData.name)
    expect((await fetchModel(page, modelId)).is_active).toBe(true)

    // The edit form shows it, switched on.
    await page.goto(`/models/${modelId}/edit`)
    const activeSwitch = page.getByRole('switch', { name: 'Active Status' })
    await expect(activeSwitch).toHaveAttribute('data-state', 'checked')
  })
})

test.describe('Model Field Validation - Complete Form', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await openDashboard(page)
  })

  test('should create model with all fields populated', async ({ page }) => {
    const testData = generateCompleteModelData()

    await page.goto('/models/new')
    await waitForModelForm(page)

    await page.locator('input[name="sku"]').fill(testData.sku)
    await page.locator('input[name="name"]').fill(testData.name)
    await page.locator('textarea[name="description"]').fill(testData.description)
    await selectOption(page, 'Category (Optional)', 'Models')
    await selectOption(page, 'Source (Optional)', testData.source)
    await selectOption(page, 'Machine (Optional)', testData.machine)
    await page.locator('input[name="labor_hours"]').fill(testData.labor_hours)
    await page.locator('input[name="overhead_percentage"]').fill(testData.overhead_percentage)
    await page.locator('input[name="print_time_hours"]').fill(testData.print_time_hours)
    await page.locator('input[name="print_time_minutes"]').fill(testData.print_time_minutes)
    await page.locator('input[name="prints_per_plate"]').fill(testData.prints_per_plate)
    await page.locator('input[name="units_in_stock"]').fill(testData.units_in_stock)

    const modelId = await submitAndVerifyModel(page, testData.name)

    const saved = await fetchModel(page, modelId)
    expect(saved.sku).toBe(testData.sku)
    expect(saved.description).toBe(testData.description)
    expect(saved.category).toBe('models')
    expect(saved.source).toBe(testData.source)
    expect(saved.machine).toBe(testData.machine)
    expect(Number(saved.labor_hours)).toBe(Number(testData.labor_hours))
    expect(Number(saved.overhead_percentage)).toBe(Number(testData.overhead_percentage))
    expect(saved.print_time_minutes).toBe(4 * 60 + 30)
    expect(saved.prints_per_plate).toBe(Number(testData.prints_per_plate))
    expect(saved.units_in_stock).toBe(Number(testData.units_in_stock))
  })

  test('should verify created model data via API', async ({ page }) => {
    const testData = generateCompleteModelData()
    const uniqueSku = `API-MOD-${Date.now()}`

    await page.goto('/models/new')
    await waitForModelForm(page)

    await page.locator('input[name="sku"]').fill(uniqueSku)
    await page.locator('input[name="name"]').fill(testData.name)
    await selectOption(page, 'Category (Optional)', 'Tools')

    const modelId = await submitModel(page)

    const data = await fetchModel(page, modelId)
    expect(data.sku).toBe(uniqueSku)
    expect(data.name).toBe(testData.name)
    expect(data.category).toBe('tools')
  })
})

test.describe('Model Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await openDashboard(page)
  })

  test('should navigate to models page', async ({ page }) => {
    await page.goto('/models')
    await expect(page).toHaveURL(/\/models/)
  })

  test('should require authentication for models page', async ({ page }) => {
    // Logout and wait for redirect to login page
    await page.goto('/logout')
    await page.waitForURL(/\/login/, { timeout: 10000 })

    // Now try to access protected route
    await page.goto('/models')
    await expect(page).toHaveURL(/\/login/)
  })
})
