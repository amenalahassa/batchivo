/**
 * E2E Test: Production Run Auto-Population from Model BOM
 *
 * Verifies that the production run wizard suggests materials from the
 * selected models' Bills of Materials (BOM).
 *
 * Flow:
 * 1. Seed spools and a model with BOM materials through the API
 * 2. Open the new production run wizard
 * 3. Select the model in Step 2
 * 4. Step 3 (Materials) suggests the BOM spools with weights scaled by quantity
 * 5. Apply suggestions; they land in the Selected Materials table
 * 6. Review and create the run
 *
 * Each test gets a fresh tenant, so the spools and models are seeded through
 * the API rather than by clicking through other screens.
 */

import { type Page } from '@playwright/test'
import { test, expect } from './fixtures'
import { apiAs, isBackendAvailable } from './helpers'

// Test data
const TEST_MODEL = {
  sku: `AUTO-TEST-${Date.now()}`,
  name: 'E2E Test Widget',
}

const TEST_SPOOLS = {
  spool1: { brand: 'eSun', color: 'Blue', name: 'eSun - PLA - Blue', weight: 50.5 },
  spool2: { brand: 'Polymaker', color: 'Red', name: 'Polymaker - PLA - Red', weight: 30.0 },
}

// ============================================
// Seeding helpers (API)
// ============================================

type Api = Awaited<ReturnType<typeof apiAs>>

async function seedSpool(
  api: Api,
  data: { brand: string; color: string; currentWeight?: number }
): Promise<string> {
  const materials = await api.get<{ id: string; code: string }[]>('/api/v1/spools/material-types')
  const pla = materials.find((m) => m.code === 'PLA') ?? materials[0]
  const filamentType = await api.post<{ id: string }>('/api/v1/filament-types', {
    material_type_id: pla.id,
    brand: data.brand,
    color: data.color,
  })
  const spool = await api.post<{ id: string }>('/api/v1/spools', {
    spool_id: `E2E-${data.brand}-${data.color}-${Math.random().toString(36).slice(2, 7)}`,
    filament_type_id: filamentType.id,
    initial_weight: 1000,
    current_weight: data.currentWeight ?? 1000,
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
    print_time_minutes: 120,
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

async function openWizard(page: Page) {
  await page.goto('/production-runs/new')
  await expect(page.getByText('Step 1 of 4: Basic Info')).toBeVisible()
}

async function nextStep(page: Page, label: string) {
  await page.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(page.getByText(label)).toBeVisible()
}

async function addModel(page: Page, sku: string, quantity: number) {
  const picker = page.getByRole('combobox').filter({ hasText: 'Select a model' })
  await expect(picker).toBeEnabled()
  await picker.click()
  // Options read "<sku> <name>": match the SKU exactly, not as a prefix
  await page
    .getByRole('option')
    .filter({ has: page.getByText(sku, { exact: true }) })
    .click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()

  const row = page.getByRole('row').filter({ has: page.getByText(sku, { exact: true }) })
  await expect(row).toBeVisible()
  await row.getByRole('spinbutton').fill(String(quantity))
}

function suggestion(page: Page, spoolName: string) {
  return page.locator('div.p-3.rounded-md.border').filter({ hasText: spoolName })
}

test.describe('Production Run Auto-Population from Model BOM', () => {
  // Signup, API seeding and a multi-step wizard: more than the default 30 s
  // when the shared stack is busy.
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async () => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
  })

  test('should auto-populate materials from model BOM when creating production run', async ({ page }) => {
    // Step 1: Seed a model with two BOM materials
    const api = await apiAs(page)
    const blueId = await seedSpool(api, TEST_SPOOLS.spool1)
    const redId = await seedSpool(api, TEST_SPOOLS.spool2)
    await seedModel(api, TEST_MODEL, [
      { spoolId: blueId, grams: TEST_SPOOLS.spool1.weight },
      { spoolId: redId, grams: TEST_SPOOLS.spool2.weight },
    ])

    // Step 2: Open the wizard and fill basic info
    await openWizard(page)
    await page.getByRole('combobox').filter({ hasText: 'Select a printer' }).click()
    await page.getByRole('option', { name: 'Prusa MK3S+' }).click()
    await page.locator('#estimated_print_time_hours_part').fill('2')

    // Step 3: Select the model with quantity 10
    await nextStep(page, 'Step 2 of 4: Models')
    await addModel(page, TEST_MODEL.sku, 10)

    // Step 4: Materials step suggests the BOM spools
    await nextStep(page, 'Step 3 of 4: Materials')
    await expect(page.getByText('Suggested Materials from Model BOM')).toBeVisible()

    // Weights scaled by quantity: 50.5g * 10 = 505g, 30.0g * 10 = 300g
    const blueSuggestion = suggestion(page, TEST_SPOOLS.spool1.name)
    await expect(blueSuggestion).toContainText('Suggested weight: 505.0g')
    await expect(blueSuggestion).toContainText('PLA')

    const redSuggestion = suggestion(page, TEST_SPOOLS.spool2.name)
    await expect(redSuggestion).toContainText('Suggested weight: 300.0g')
    await expect(redSuggestion).toContainText('PLA')

    // Step 5: Apply all suggestions
    await page.getByRole('button', { name: 'Apply All Suggestions' }).click()

    // Materials are now in the Selected Materials table with their weights
    await expect(page.getByText('Selected Materials (2)')).toBeVisible()
    const blueRow = page.getByRole('row').filter({ hasText: TEST_SPOOLS.spool1.name })
    await expect(blueRow.getByRole('spinbutton').first()).toHaveValue('505')
    await expect(blueRow).toContainText('505.0g')
    const redRow = page.getByRole('row').filter({ hasText: TEST_SPOOLS.spool2.name })
    await expect(redRow.getByRole('spinbutton').first()).toHaveValue('300')
    await expect(redRow).toContainText('300.0g')

    // The suggestions are now marked as "Added"
    await expect(blueSuggestion.getByText('Added', { exact: true })).toBeVisible()
    await expect(redSuggestion.getByText('Added', { exact: true })).toBeVisible()

    // Step 6: Review
    await nextStep(page, 'Step 4 of 4: Review')
    const modelRow = page.getByRole('row').filter({ hasText: TEST_MODEL.sku })
    await expect(modelRow).toContainText(TEST_MODEL.name)
    await expect(modelRow.getByRole('cell', { name: '10', exact: true })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: TEST_SPOOLS.spool1.name })).toContainText(
      '505.0g'
    )
    await expect(page.getByRole('row').filter({ hasText: TEST_SPOOLS.spool2.name })).toContainText(
      '300.0g'
    )

    // Step 7: Create the run and land on its detail page
    await page.getByRole('button', { name: 'Create Production Run' }).click()
    await page.waitForURL(/\/production-runs\/[a-f0-9-]+$/, { timeout: 15000 })
    await expect(page.getByText('In Progress', { exact: true })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: TEST_MODEL.sku })).toContainText(
      TEST_MODEL.name
    )
    await expect(page.getByRole('row').filter({ hasText: 'eSun' })).toContainText('505.0')
    await expect(page.getByRole('row').filter({ hasText: 'Polymaker' })).toContainText('300.0')
  })

  test('should handle low inventory warning when applying suggestions', async ({ page }) => {
    // A spool with only 100g left, on a model that needs 50.5g per item
    const api = await apiAs(page)
    const lowId = await seedSpool(api, { ...TEST_SPOOLS.spool1, currentWeight: 100 })
    await seedModel(api, TEST_MODEL, [{ spoolId: lowId, grams: TEST_SPOOLS.spool1.weight }])

    await openWizard(page)
    await nextStep(page, 'Step 2 of 4: Models')
    // 10 items need 505g: more than the 100g available
    await addModel(page, TEST_MODEL.sku, 10)
    await nextStep(page, 'Step 3 of 4: Materials')

    // The suggestion is flagged "Low Inventory" with the warning styling
    const lowSuggestion = suggestion(page, TEST_SPOOLS.spool1.name)
    await expect(lowSuggestion.getByText('Low Inventory', { exact: true })).toBeVisible()
    await expect(lowSuggestion).toContainText('Available: 100g')
    await expect(lowSuggestion).toHaveClass(/bg-destructive\/10/)
  })

  test('should handle inactive spool warning when applying suggestions', async ({ page }) => {
    // A model whose BOM spool has since been archived (inactive)
    const api = await apiAs(page)
    const spoolId = await seedSpool(api, TEST_SPOOLS.spool1)
    await seedModel(api, TEST_MODEL, [{ spoolId, grams: TEST_SPOOLS.spool1.weight }])
    await api.put(`/api/v1/spools/${spoolId}`, { is_active: false })

    await openWizard(page)
    await nextStep(page, 'Step 2 of 4: Models')
    await addModel(page, TEST_MODEL.sku, 1)
    await nextStep(page, 'Step 3 of 4: Materials')

    // The suggestion is flagged "Inactive" with the warning styling
    const inactiveSuggestion = suggestion(page, TEST_SPOOLS.spool1.name)
    await expect(inactiveSuggestion.getByText('Inactive', { exact: true })).toBeVisible()
    await expect(inactiveSuggestion).toHaveClass(/bg-destructive\/10/)
  })

  test('should show per-model breakdown when multiple models use same spool', async ({ page }) => {
    // Two models that both use the Blue PLA spool
    const api = await apiAs(page)
    const blueId = await seedSpool(api, TEST_SPOOLS.spool1)
    const secondModel = { sku: `${TEST_MODEL.sku}-B`, name: 'E2E Second Widget' }
    await seedModel(api, TEST_MODEL, [{ spoolId: blueId, grams: TEST_SPOOLS.spool1.weight }])
    await seedModel(api, secondModel, [{ spoolId: blueId, grams: 20 }])

    await openWizard(page)
    await nextStep(page, 'Step 2 of 4: Models')
    await addModel(page, TEST_MODEL.sku, 2)
    await addModel(page, secondModel.sku, 3)
    await nextStep(page, 'Step 3 of 4: Materials')

    // One combined suggestion: 50.5 * 2 + 20 * 3 = 161g
    const blueSuggestion = suggestion(page, TEST_SPOOLS.spool1.name)
    await expect(blueSuggestion).toHaveCount(1)
    await expect(blueSuggestion).toContainText('Suggested weight: 161.0g')

    // Expand the details to see the per-model breakdown
    await blueSuggestion.getByText('Used in 2 models').click()
    await expect(blueSuggestion.getByText(`${TEST_MODEL.sku}: 101.0g (qty: 2)`)).toBeVisible()
    await expect(blueSuggestion.getByText(`${secondModel.sku}: 60.0g (qty: 3)`)).toBeVisible()
  })
})
