/**
 * E2E Tests: Inventory - Filament Library (spools)
 *
 * Tests the filament inventory at /filaments (/inventory redirects there):
 * - Viewing the library, its controls and empty state
 * - Adding filament (one filament type + N spools) through "Add Filament"
 * - Search and the quick filter toggles
 * - Updating a spool's weight on its quick-update page (the QR code target)
 *
 * The library lists filament types; a type's spools are shown in a read-only
 * sheet. There is no per-spool delete in the UI.
 *
 * Prerequisites:
 * - Frontend dev server running
 * - Backend API running with E2E_TEST_HOOKS_ENABLED (see e2e/README.md)
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

interface BulkCreateResult {
  filament_type_id: string
  spool_ids: string[]
}

function generateTestSpoolData() {
  const suffix = uniqueSuffix()
  return {
    brand: `TestBrand-${suffix}`,
    color: `TestColor-${suffix}`,
    initialWeight: 1000,
  }
}

/** Seed a filament type with `quantity` spools through the API. */
async function seedFilament(
  page: Page,
  data: { brand: string; color: string; initialWeight?: number; quantity?: number }
): Promise<BulkCreateResult> {
  const api = await apiAs(page)
  const [material] = await api.get<MaterialType[]>('/api/v1/spools/material-types')
  return api.post<BulkCreateResult>('/api/v1/filament-types/bulk-create', {
    material_type_id: material.id,
    brand: data.brand,
    color: data.color,
    quantity: data.quantity ?? 1,
    initial_weight: data.initialWeight ?? 1000,
  })
}

/** Open "Add Filament" and pick "Batch of identical spools". */
async function openAddFilamentForm(page: Page): Promise<Locator> {
  await page.getByRole('button', { name: 'Add Filament' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByText('Batch of identical spools').click()
  await expect(dialog.getByRole('heading', { name: 'Add filament — batch' })).toBeVisible()
  return dialog
}

/** Fill the required fields of the batch form and submit it. */
async function fillAndSubmitFilamentForm(
  page: Page,
  dialog: Locator,
  data: { brand: string; color: string; initialWeight: number }
) {
  await dialog.getByLabel('Brand').fill(data.brand)
  await dialog.getByLabel('Color', { exact: true }).fill(data.color)
  await dialog.getByRole('combobox', { name: 'Material type' }).click()
  await page.getByRole('option').first().click()
  await dialog.getByLabel('Weight per spool (g)').fill(data.initialWeight.toString())

  await dialog.getByRole('button', { name: 'Add spools' }).click()
  await expect(dialog).toBeHidden({ timeout: 15000 })
}

function libraryRow(page: Page, brand: string): Locator {
  return page.getByRole('row', { name: new RegExp(brand) })
}

test.describe('Inventory Page - Display', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/inventory')
  })

  test('should display inventory page with all elements', async ({ page }) => {
    // /inventory is the legacy route: it lands on the Filament Library.
    await expect(page).toHaveURL(/\/filaments$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Filament Library' })).toBeVisible()

    await expect(page.getByRole('button', { name: 'Add Filament' })).toBeVisible()

    // Search and filters
    await expect(page.getByPlaceholder(/search/i)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Filters' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Needs labels' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'No sample' })).toBeVisible()
  })

  test('should show empty state for new user', async ({ page }) => {
    await expect(page.getByText('No filament types yet')).toBeVisible()
    await expect(page.getByText('Add your first filament type to get started.')).toBeVisible()
    await expect(page.getByRole('table')).toHaveCount(0)
  })
})

test.describe('Inventory - Add Spool', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
    await page.goto('/filaments')
  })

  test('should open add spool dialog', async ({ page }) => {
    await page.getByRole('button', { name: 'Add Filament' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(
      dialog.getByRole('heading', { name: 'How would you like to add filament?' })
    ).toBeVisible()
    await expect(dialog.getByText('Batch of identical spools')).toBeVisible()
    await expect(dialog.getByText('Multiple color variants')).toBeVisible()

    // The batch form has the filament fields
    await dialog.getByText('Batch of identical spools').click()
    await expect(dialog.getByLabel('Brand')).toBeVisible()
    await expect(dialog.getByLabel('Color', { exact: true })).toBeVisible()
  })

  test('should create a new spool with required fields', async ({ page }) => {
    const testData = generateTestSpoolData()

    const dialog = await openAddFilamentForm(page)
    await fillAndSubmitFilamentForm(page, dialog, testData)

    const row = libraryRow(page, testData.brand)
    await expect(row).toBeVisible({ timeout: 10000 })
    await expect(row.getByText('1 spools')).toBeVisible()
  })

  test('should close dialog on cancel', async ({ page }) => {
    await page.getByRole('button', { name: 'Add Filament' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // The dialog has no Cancel button: it closes with its Close (X) button.
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(dialog).toBeHidden({ timeout: 5000 })

    // And with Escape
    await page.getByRole('button', { name: 'Add Filament' }).click()
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden({ timeout: 5000 })
  })
})

test.describe('Inventory - Search and Filter', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
  })

  test('should filter spools by search term', async ({ page }) => {
    const suffix = uniqueSuffix()
    const uniqueBrand = `UniqueSearchTest-${suffix}`
    const otherBrand = `OtherBrand-${suffix}`
    await seedFilament(page, { brand: uniqueBrand, color: 'Red' })
    await seedFilament(page, { brand: otherBrand, color: 'Blue' })

    await page.goto('/filaments')
    await expect(libraryRow(page, uniqueBrand)).toBeVisible()
    await expect(libraryRow(page, otherBrand)).toBeVisible()

    await page.getByPlaceholder(/search/i).fill(uniqueBrand)

    await expect(libraryRow(page, uniqueBrand)).toBeVisible()
    await expect(libraryRow(page, otherBrand)).toBeHidden()
  })

  test('should toggle needs labels filter', async ({ page }) => {
    // A new spool has no label yet, so it shows under "Needs labels".
    const testData = generateTestSpoolData()
    await seedFilament(page, testData)
    await page.goto('/filaments')
    await expect(libraryRow(page, testData.brand)).toBeVisible()

    const needsLabels = page.getByRole('button', { name: 'Needs labels' })
    await expect(needsLabels).toHaveAttribute('aria-pressed', 'false')
    await needsLabels.click()
    await expect(needsLabels).toHaveAttribute('aria-pressed', 'true')
    await expect(libraryRow(page, testData.brand)).toBeVisible()

    await needsLabels.click()
    await expect(needsLabels).toHaveAttribute('aria-pressed', 'false')
    await expect(page).toHaveURL(/\/filaments/)
  })
})

test.describe('Inventory - Update Weight', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
  })

  test('should update spool weight', async ({ page }) => {
    const testData = generateTestSpoolData()
    const created = await seedFilament(page, testData)
    const api = await apiAs(page)
    const [spool] = await api.get<Array<{ id: string; spool_id: string }>>(
      `/api/v1/filament-types/${created.filament_type_id}/spools`
    )

    // The spool's quick-update page (what its QR label opens)
    await page.goto(`/filaments/${spool.id}/update`)
    await expect(page.getByText(spool.spool_id, { exact: true })).toBeVisible()
    await expect(page.getByText('1000g').first()).toBeVisible()

    await page.getByLabel('Filament Used (grams)').fill('200')
    await page.getByRole('button', { name: 'Update Weight' }).click()

    // Saving returns to the dashboard
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 })
    const updated = await api.get<{ current_weight: number | string }>(`/api/v1/spools/${spool.id}`)
    expect(parseFloat(String(updated.current_weight))).toBe(800)

    // The library's spool sheet shows the new weight
    await page.goto('/filaments')
    await libraryRow(page, testData.brand).click()
    await expect(page.getByRole('dialog').getByRole('cell', { name: '800g / 1000g' })).toBeVisible()
  })
})

test.describe('Inventory - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await registerAndLogin(page)
  })

  test('should navigate to inventory from dashboard', async ({ page }) => {
    await page.goto('/dashboard')

    await page.getByRole('navigation').getByRole('link', { name: 'Filaments', exact: true }).click()
    await expect(page).toHaveURL(/\/filaments/)
    await expect(page.getByRole('heading', { level: 1, name: 'Filament Library' })).toBeVisible()
  })

  test('should require authentication for inventory page', async ({ page, browserName }) => {
    // Skip on WebKit due to redirect timeout issues in test environment
    test.skip(browserName === 'webkit', 'WebKit has redirect timeout issues in test env')

    await page.goto('/logout')
    await page.waitForURL(/\/login/, { timeout: 10000 })

    // Both the legacy and the current route send a signed-out user to login
    await page.goto('/inventory')
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/filaments')
    await expect(page).toHaveURL(/\/login/)
  })
})
