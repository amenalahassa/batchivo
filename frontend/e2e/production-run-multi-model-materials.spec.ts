/**
 * E2E Test: Multi-Model Production Run with Grouped Materials
 *
 * Verifies the material grouping when a production run includes several
 * models that share materials.
 *
 * Flow:
 * 1. Seed Model A with BOM (PLA-Blue: 50g, PLA-Red: 30g)
 * 2. Seed Model B with BOM (PLA-Red: 40g, PLA-Green: 60g)
 * 3. Create a production run selecting both models
 * 4. Verify the suggestions are grouped by spool:
 *    - PLA-Blue: 50g total (used in 1 model)
 *    - PLA-Red: 70g total (used in 2 models)
 *    - PLA-Green: 60g total (used in 1 model)
 * 5. Verify the expandable per-model breakdown
 * 6. Apply the suggestions
 * 7. Create the production run and check its materials
 *
 * Each test gets a fresh tenant, so spools and models are seeded through the
 * API rather than by clicking through other screens.
 */

import { type Page } from '@playwright/test'
import { test, expect } from './fixtures'
import { apiAs, isBackendAvailable } from './helpers'

const SPOOLS = {
  blue: { brand: 'E2E', color: 'Blue', name: 'E2E - PLA - Blue' },
  red: { brand: 'E2E', color: 'Red', name: 'E2E - PLA - Red' },
  green: { brand: 'E2E', color: 'Green', name: 'E2E - PLA - Green' },
}

const MODEL_A = { name: 'Widget A', sku: 'WGT-A-001' }
const MODEL_B = { name: 'Widget B', sku: 'WGT-B-001' }

// ============================================
// Seeding helpers (API)
// ============================================

type Api = Awaited<ReturnType<typeof apiAs>>

async function seedSpool(api: Api, data: { brand: string; color: string }): Promise<string> {
  const materials = await api.get<{ id: string; code: string }[]>('/api/v1/spools/material-types')
  const pla = materials.find((m) => m.code === 'PLA') ?? materials[0]
  const filamentType = await api.post<{ id: string }>('/api/v1/filament-types', {
    material_type_id: pla.id,
    brand: data.brand,
    color: data.color,
  })
  const spool = await api.post<{ id: string }>('/api/v1/spools', {
    spool_id: `E2E-${data.color}-${Math.random().toString(36).slice(2, 7)}`,
    filament_type_id: filamentType.id,
    initial_weight: 1000,
    current_weight: 1000,
    purchase_price: '25.00',
  })
  return spool.id
}

async function seedModel(
  api: Api,
  data: { sku: string; name: string },
  bom: { spoolId: string; grams: number }[]
): Promise<string> {
  const model = await api.post<{ id: string }>('/api/v1/models', {
    sku: data.sku,
    name: data.name,
    prints_per_plate: 1,
    print_time_minutes: 150,
  })
  for (const line of bom) {
    await api.post(`/api/v1/models/${model.id}/materials`, {
      spool_id: line.spoolId,
      weight_grams: String(line.grams),
    })
  }
  return model.id
}

// ============================================
// Wizard helpers (UI)
// ============================================

async function nextStep(page: Page, label: string) {
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText(label)).toBeVisible()
}

async function addModel(page: Page, sku: string) {
  const picker = page.getByRole('combobox').filter({ hasText: 'Select a model' })
  await expect(picker).toBeEnabled()
  await picker.click()
  await page
    .getByRole('option')
    .filter({ has: page.getByText(sku, { exact: true }) })
    .click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByRole('row').filter({ has: page.getByText(sku, { exact: true }) })).toBeVisible()
}

function suggestion(page: Page, spoolName: string) {
  return page.locator('div.p-3.rounded-md.border').filter({ hasText: spoolName })
}

test.describe('Multi-Model Production Run with Grouped Materials', () => {
  // Signup, API seeding and a multi-step wizard: more than the default 30 s
  // when the shared stack is busy.
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async () => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
  })

  test('should group materials by spool across multiple models with correct totals', async ({
    page,
  }) => {
    // ============================================
    // PART 1-2: Seed both models with their BOMs
    // ============================================
    const api = await apiAs(page)
    const blueId = await seedSpool(api, SPOOLS.blue)
    const redId = await seedSpool(api, SPOOLS.red)
    const greenId = await seedSpool(api, SPOOLS.green)
    await seedModel(api, MODEL_A, [
      { spoolId: blueId, grams: 50 },
      { spoolId: redId, grams: 30 },
    ])
    await seedModel(api, MODEL_B, [
      { spoolId: redId, grams: 40 },
      { spoolId: greenId, grams: 60 },
    ])

    // ============================================
    // PART 3: Create production run with both models
    // ============================================
    await page.goto('/production-runs/new')
    await expect(page.getByText('Step 1 of 4: Basic Info')).toBeVisible()

    await page.getByRole('combobox').filter({ hasText: 'Select a printer' }).click()
    await page.getByRole('option', { name: 'Prusa MK3S+' }).click()
    await page.locator('#estimated_print_time_hours_part').fill('6')
    await page.locator('#bed_temperature').fill('60')
    await page.locator('#nozzle_temperature').fill('210')

    await nextStep(page, 'Step 2 of 4: Models')
    // Each model is added with the default quantity of 1
    await addModel(page, MODEL_A.sku)
    await addModel(page, MODEL_B.sku)
    await expect(page.getByText('Selected Models (2)')).toBeVisible()

    await nextStep(page, 'Step 3 of 4: Materials')

    // ============================================
    // PART 4: Verify material grouping
    // ============================================
    await expect(page.getByText('Suggested Materials from Model BOM')).toBeVisible()

    const blue = suggestion(page, SPOOLS.blue.name)
    await expect(blue).toContainText('Suggested weight: 50.0g')
    await expect(blue).toContainText('Used in 1 model')

    const red = suggestion(page, SPOOLS.red.name)
    await expect(red).toContainText('Suggested weight: 70.0g')
    await expect(red).toContainText('Used in 2 models')

    const green = suggestion(page, SPOOLS.green.name)
    await expect(green).toContainText('Suggested weight: 60.0g')
    await expect(green).toContainText('Used in 1 model')

    // ============================================
    // PART 5: Verify expandable per-model breakdown
    // ============================================
    await red.getByText('Used in 2 models').click()
    await expect(red.getByText(`${MODEL_A.sku}: 30.0g (qty: 1)`)).toBeVisible()
    await expect(red.getByText(`${MODEL_B.sku}: 40.0g (qty: 1)`)).toBeVisible()

    // ============================================
    // PART 6: Apply material suggestions
    // ============================================
    await page.getByRole('button', { name: 'Apply All Suggestions' }).click()
    await expect(page.getByText('Selected Materials (3)')).toBeVisible()

    await nextStep(page, 'Step 4 of 4: Review')

    // Review shows both models and the grouped materials
    await expect(page.getByRole('row').filter({ hasText: MODEL_A.sku })).toContainText(MODEL_A.name)
    await expect(page.getByRole('row').filter({ hasText: MODEL_B.sku })).toContainText(MODEL_B.name)
    await expect(page.getByRole('row').filter({ hasText: SPOOLS.blue.name })).toContainText('50.0g')
    await expect(page.getByRole('row').filter({ hasText: SPOOLS.red.name })).toContainText('70.0g')
    await expect(page.getByRole('row').filter({ hasText: SPOOLS.green.name })).toContainText('60.0g')

    // ============================================
    // PART 7: Complete production run creation
    // ============================================
    await page.getByRole('button', { name: 'Create Production Run' }).click()
    await page.waitForURL(/\/production-runs\/[a-f0-9-]+$/, { timeout: 15000 })

    await expect(page.getByText('In Progress', { exact: true })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: MODEL_A.sku })).toContainText(MODEL_A.name)
    await expect(page.getByRole('row').filter({ hasText: MODEL_B.sku })).toContainText(MODEL_B.name)

    // The materials table lists the 3 grouped spools with their weights
    const materialsTable = page.getByRole('table').filter({ hasText: 'Est. Model (g)' })
    await expect(materialsTable.getByRole('row')).toHaveCount(4) // header + 3 spools
    await expect(materialsTable.getByRole('row').filter({ hasText: 'Blue' })).toContainText('50.0')
    await expect(materialsTable.getByRole('row').filter({ hasText: 'Red' })).toContainText('70.0')
    await expect(materialsTable.getByRole('row').filter({ hasText: 'Green' })).toContainText('60.0')
  })
})
