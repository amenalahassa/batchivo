/**
 * E2E Test: Production Run Creation Workflow with Inventory Deduction
 *
 * Verifies the production run workflow including:
 * 1. A model with BOM materials (seeded through the API)
 * 2. Creating a production run through the wizard
 * 3. Completing the production run
 * 4. Spool weights are deducted correctly
 *
 * Each test gets a fresh tenant, so the spool and model are seeded through
 * the API rather than by clicking through other screens.
 */

import { test, expect, type Page } from '@playwright/test'
import { apiAs, isBackendAvailable, registerAndLogin } from '../../helpers'

// Generate unique test identifiers
const TIMESTAMP = Date.now()

// Test spool data
const TEST_SPOOL = {
  brand: `TestBrand-${TIMESTAMP}`,
  color: 'Blue',
  initialWeight: 1000, // grams
  currentWeight: 1000, // grams
}

// Test model data
const TEST_MODEL = {
  name: `Test Model ${TIMESTAMP}`,
  sku: `TST-${TIMESTAMP}`,
  materialWeightPerItem: 50, // grams per item
}

// Production run data
const PRODUCTION_QUANTITY = 5 // Will use 250g total (50g × 5)

type Api = Awaited<ReturnType<typeof apiAs>>

/**
 * Helper: Seed a spool and return its ID
 */
async function createTestSpool(
  api: Api,
  data: { brand: string; color: string; initialWeight: number; currentWeight: number }
): Promise<string> {
  const materials = await api.get<{ id: string; code: string }[]>('/api/v1/spools/material-types')
  const pla = materials.find((m) => m.code === 'PLA') ?? materials[0]
  const filamentType = await api.post<{ id: string }>('/api/v1/filament-types', {
    material_type_id: pla.id,
    brand: data.brand,
    color: data.color,
  })
  const spool = await api.post<{ id: string }>('/api/v1/spools', {
    spool_id: `E2E-${Math.random().toString(36).slice(2, 9)}`,
    filament_type_id: filamentType.id,
    initial_weight: data.initialWeight,
    current_weight: data.currentWeight,
    purchase_price: '25.00',
  })
  return spool.id
}

/**
 * Helper: Get the current weight of a spool
 */
async function getSpoolWeight(api: Api, spoolId: string): Promise<number> {
  const spool = await api.get<{ current_weight: number | string }>(`/api/v1/spools/${spoolId}`)
  return Number(spool.current_weight)
}

/**
 * Helper: Seed a model whose BOM uses the spool
 */
async function createTestModel(api: Api, spoolId: string, gramsPerItem: number): Promise<string> {
  const model = await api.post<{ id: string }>('/api/v1/models', {
    sku: TEST_MODEL.sku,
    name: TEST_MODEL.name,
    prints_per_plate: 1,
    print_time_minutes: 120,
  })
  await api.post(`/api/v1/models/${model.id}/materials`, {
    spool_id: spoolId,
    weight_grams: String(gramsPerItem),
  })
  return model.id
}

/**
 * Helper: Walk the wizard to the Materials step with the model and quantity
 */
async function wizardToMaterials(
  page: Page,
  modelSku: string,
  quantity: number,
  printHours?: number
) {
  await page.goto('/production-runs')
  await page.getByRole('link', { name: 'New Production Run' }).click()
  await expect(page.getByText('Step 1 of 4: Basic Info')).toBeVisible()

  await page.getByRole('combobox').filter({ hasText: 'Select a printer' }).click()
  await page.getByRole('option', { name: 'Bambu Lab P1S' }).click()
  if (printHours !== undefined) {
    await page.locator('#estimated_print_time_hours_part').fill(String(printHours))
  }

  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText('Step 2 of 4: Models')).toBeVisible()

  const picker = page.getByRole('combobox').filter({ hasText: 'Select a model' })
  await expect(picker).toBeEnabled()
  await picker.click()
  await page
    .getByRole('option')
    .filter({ has: page.getByText(modelSku, { exact: true }) })
    .click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const row = page.getByRole('row').filter({ has: page.getByText(modelSku, { exact: true }) })
  await row.getByRole('spinbutton').fill(quantity.toString())

  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText('Step 3 of 4: Materials')).toBeVisible()
}

/**
 * Helper: Create and complete a production run
 */
async function createAndCompleteProductionRun(
  page: Page,
  modelSku: string,
  quantity: number,
  printHours?: number
): Promise<string> {
  await wizardToMaterials(page, modelSku, quantity, printHours)

  // Apply the material suggestions from the model's BOM
  await page.getByRole('button', { name: 'Apply All Suggestions' }).click()
  await expect(page.getByText('Selected Materials (1)')).toBeVisible()

  // Review and create
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText('Step 4 of 4: Review')).toBeVisible()
  await page.getByRole('button', { name: 'Create Production Run' }).click()
  await page.waitForURL(/\/production-runs\/[a-f0-9-]+$/, { timeout: 15000 })
  const runId = page.url().split('/').pop()!

  // Complete the production run, confirming the estimated weights as actual
  await page.getByRole('button', { name: 'Complete Run' }).click()
  const dialog = page.getByRole('dialog').filter({ hasText: 'Complete Production Run' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Complete Run' }).click()
  await expect(dialog).toBeHidden({ timeout: 30000 })

  // Status badge in the header, beside the Edit Run button
  await expect(
    page.getByRole('button', { name: 'Edit Run' }).locator('..').getByText('Completed', { exact: true })
  ).toBeVisible()

  return runId
}

test.describe('Production Run Workflow with Inventory Deduction', () => {
  // Signup, API seeding and a multi-step wizard: more than the default 30 s
  // when the shared stack is busy.
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
  })

  test('should deduct inventory when production run is completed', async ({ page }) => {
    const api = await apiAs(page)

    // Step 1: Create test spool
    const spoolId = await createTestSpool(api, TEST_SPOOL)
    expect(spoolId).toBeTruthy()

    // Step 2: Record initial spool weight
    const initialWeight = await getSpoolWeight(api, spoolId)
    expect(initialWeight).toBe(TEST_SPOOL.currentWeight)

    // Step 3: Create test model with BOM
    const modelId = await createTestModel(api, spoolId, TEST_MODEL.materialWeightPerItem)
    expect(modelId).toBeTruthy()

    // Step 4: Create and complete production run, with a print time entered so
    // the completion dialog sends a duration (the run without one is covered
    // by the west-of-UTC test below).
    const runId = await createAndCompleteProductionRun(
      page,
      TEST_MODEL.sku,
      PRODUCTION_QUANTITY,
      2
    )
    expect(runId).toBeTruthy()

    // Step 5: Verify inventory was deducted
    const expectedDeduction = TEST_MODEL.materialWeightPerItem * PRODUCTION_QUANTITY // 50g × 5 = 250g
    const expectedFinalWeight = initialWeight - expectedDeduction // 1000g - 250g = 750g

    const finalWeight = await getSpoolWeight(api, spoolId)

    // Allow small floating point tolerance
    expect(finalWeight).toBeCloseTo(expectedFinalWeight, 1)
  })

  test('should show warning when production run requires more material than available', async ({
    page,
  }) => {
    const api = await apiAs(page)

    // A low stock spool: only 50g available
    const lowStockSpool = {
      brand: `LowStock-${Date.now()}`,
      color: 'Red',
      initialWeight: 100,
      currentWeight: 50,
    }
    const spoolId = await createTestSpool(api, lowStockSpool)
    await createTestModel(api, spoolId, TEST_MODEL.materialWeightPerItem)

    // 5 items need 250g: more than the 50g on the spool
    await wizardToMaterials(page, TEST_MODEL.sku, PRODUCTION_QUANTITY)

    // The material suggestion carries a "Low Inventory" warning
    const lowSuggestion = page
      .locator('div.p-3.rounded-md.border')
      .filter({ hasText: `${lowStockSpool.brand} - PLA - ${lowStockSpool.color}` })
    await expect(lowSuggestion).toContainText('Suggested weight: 250.0g')
    await expect(lowSuggestion).toContainText('Available: 50g')
    await expect(lowSuggestion.getByText('Low Inventory', { exact: true })).toBeVisible()
  })
})

test.describe('Production Run completion west of UTC', () => {
  test.describe.configure({ timeout: 90_000 })

  // The browser runs behind UTC, as for an operator in North America.
  test.use({ timezoneId: 'America/New_York' })

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
  })

  // Regression: .specify/bugs/complete-run-timezone-500 (the "Started" field
  // mixed UTC and local time, which gave a negative duration and a 500)
  test('completes a run that has no estimated print time', async ({ page }) => {
    const api = await apiAs(page)
    const spoolId = await createTestSpool(api, TEST_SPOOL)
    await createTestModel(api, spoolId, TEST_MODEL.materialWeightPerItem)

    // No print time entered: the completion dialog leaves the duration blank
    await createAndCompleteProductionRun(page, TEST_MODEL.sku, 1)

    expect(await getSpoolWeight(api, spoolId)).toBeCloseTo(
      TEST_SPOOL.currentWeight - TEST_MODEL.materialWeightPerItem,
      1
    )
  })
})
