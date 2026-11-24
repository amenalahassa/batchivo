/**
 * E2E Test: Production Run Edit Flow with Status-Based Restrictions
 *
 * Verifies editing production runs with status-based restrictions.
 *
 * Flow:
 * 1. Seed an in_progress production run (one model, one spool) through the API
 * 2. Edit the run - all fields are editable
 * 3. Save changes and verify they persisted
 * 4. Complete the production run
 * 5. Edit the completed run - only the notes field is editable
 * 6. The immutable status alert is shown
 * 7. Save a notes-only change
 * 8. Other fields remain unchanged
 *
 * Each test gets a fresh tenant; the run and what it prints are seeded
 * through the API, the wizard itself is covered by the other production run
 * specs.
 */

import { test, expect, type Page } from '@playwright/test'
import { apiAs, isBackendAvailable, registerAndLogin } from './helpers'

// Test data
const TEST_RUN = {
  printer: 'Prusa i3 MK3S',
  estimatedTime: '2.5',
  bedTemp: 60,
  nozzleTemp: 210,
  notes: 'Initial test notes',
}

const EDIT_DATA = {
  printer: 'Prusa XL',
  estimatedTime: '3',
  bedTemp: '65',
  nozzleTemp: '215',
  notes: 'Updated notes after editing',
}

const COMPLETED_NOTES = 'Added notes after completion'

/**
 * Seed an in_progress run printing one model from one spool, and open it.
 */
async function createProductionRun(page: Page): Promise<string> {
  const api = await apiAs(page)
  const materials = await api.get<{ id: string; code: string }[]>('/api/v1/spools/material-types')
  const pla = materials.find((m) => m.code === 'PLA') ?? materials[0]
  const filamentType = await api.post<{ id: string }>('/api/v1/filament-types', {
    material_type_id: pla.id,
    brand: 'E2E',
    color: 'Blue',
  })
  const spool = await api.post<{ id: string }>('/api/v1/spools', {
    spool_id: `E2E-EDIT-${Math.random().toString(36).slice(2, 7)}`,
    filament_type_id: filamentType.id,
    initial_weight: 1000,
    current_weight: 1000,
    purchase_price: '25.00',
  })
  const model = await api.post<{ id: string }>('/api/v1/models', {
    sku: `EDIT-${Date.now()}`,
    name: 'Edit Flow Widget',
  })
  const run = await api.post<{ id: string }>('/api/v1/production-runs', {
    status: 'in_progress',
    started_at: new Date().toISOString(),
    printer_name: TEST_RUN.printer,
    estimated_print_time_hours: TEST_RUN.estimatedTime,
    bed_temperature: TEST_RUN.bedTemp,
    nozzle_temperature: TEST_RUN.nozzleTemp,
    notes: TEST_RUN.notes,
    items: [{ model_id: model.id, quantity: 2 }],
    materials: [{ spool_id: spool.id, estimated_model_weight_grams: '40' }],
  })

  await page.goto(`/production-runs/${run.id}`)
  await expect(statusBadge(page, 'In Progress')).toBeVisible()
  return run.id
}

/** The status badge in the run header, beside the Edit Run button. */
function statusBadge(page: Page, status: string) {
  return page.getByRole('button', { name: 'Edit Run' }).locator('..').getByText(status, { exact: true })
}

function editDialog(page: Page) {
  return page.getByRole('dialog').filter({ hasText: 'Edit Production Run' })
}

async function openEditDialog(page: Page) {
  await page.getByRole('button', { name: 'Edit Run' }).click()
  await expect(editDialog(page)).toBeVisible()
  return editDialog(page)
}

test.describe('Production Run Edit Flow with Status-Based Restrictions', () => {
  // Signup, API seeding and a multi-step wizard: more than the default 30 s
  // when the shared stack is busy.
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    await registerAndLogin(page)
  })

  test('should allow full editing of in_progress run and restrict editing after completion', async ({ page }) => {
    // ============================================
    // PART 1: Create in_progress production run
    // ============================================
    await createProductionRun(page)

    await expect(page.getByText(TEST_RUN.printer, { exact: true })).toBeVisible()
    await expect(page.getByText(TEST_RUN.notes, { exact: true })).toBeVisible()

    // ============================================
    // PART 2: Edit in_progress run (full access)
    // ============================================
    let dialog = await openEditDialog(page)

    // No lock alert (run is editable)
    await expect(dialog.getByText('Only notes can be edited')).toBeHidden()

    // All tabs are available
    await expect(dialog.getByRole('tab', { name: 'Basic Info' })).toBeVisible()
    await expect(dialog.getByRole('tab', { name: /^Items/ })).toBeVisible()
    await expect(dialog.getByRole('tab', { name: /^Materials/ })).toBeVisible()

    // Edit basic info fields
    await dialog.getByLabel('Printer Name').fill(EDIT_DATA.printer)
    await dialog.getByLabel('Estimated Print Time (hours)').fill(EDIT_DATA.estimatedTime)
    await dialog.getByLabel('Bed Temperature (°C)').fill(EDIT_DATA.bedTemp)
    await dialog.getByLabel('Nozzle Temperature (°C)').fill(EDIT_DATA.nozzleTemp)

    // Update notes
    await dialog.getByLabel('Notes').fill(EDIT_DATA.notes)

    // Save is enabled (changes detected)
    const saveButton = dialog.getByRole('button', { name: 'Save Changes' })
    await expect(saveButton).toBeEnabled()
    await saveButton.click()
    await expect(dialog).toBeHidden()

    // ============================================
    // PART 3: Verify changes persisted
    // ============================================
    await page.reload()

    await expect(page.getByText(EDIT_DATA.printer, { exact: true })).toBeVisible()
    await expect(page.getByText(EDIT_DATA.notes, { exact: true })).toBeVisible()
    await expect(page.getByText(`${EDIT_DATA.bedTemp}°C`, { exact: true })).toBeVisible()
    await expect(page.getByText(`${EDIT_DATA.nozzleTemp}°C`, { exact: true })).toBeVisible()

    // ============================================
    // PART 4: Complete the production run
    // ============================================
    await page.getByRole('button', { name: 'Complete Run' }).click()
    const completeDialog = page.getByRole('dialog').filter({ hasText: 'Complete Production Run' })
    await expect(completeDialog).toBeVisible()

    // Actual weights default to the estimates; confirm as-is
    await completeDialog.getByRole('button', { name: 'Complete Run' }).click()
    await expect(completeDialog).toBeHidden({ timeout: 30000 })

    await expect(statusBadge(page, 'Completed')).toBeVisible()

    // ============================================
    // PART 5: Try to edit completed run (restricted)
    // ============================================
    dialog = await openEditDialog(page)

    // Lock alert appears
    await expect(dialog.getByText(/This run is completed\. Only notes can be edited\./)).toBeVisible()

    // Tabs are hidden for immutable runs
    await expect(dialog.getByRole('tab')).toHaveCount(0)
    await expect(dialog.getByLabel('Printer Name')).toBeHidden()

    // Only notes are editable
    const notesOnlyField = dialog.getByLabel('Notes')
    await expect(notesOnlyField).toBeEditable()
    await notesOnlyField.fill(COMPLETED_NOTES)

    const saveButtonRestricted = dialog.getByRole('button', { name: 'Save Changes' })
    await expect(saveButtonRestricted).toBeEnabled()
    await saveButtonRestricted.click()
    await expect(dialog).toBeHidden()

    // ============================================
    // PART 6: Verify only notes changed, other fields unchanged
    // ============================================
    await page.reload()

    await expect(page.getByText(COMPLETED_NOTES, { exact: true })).toBeVisible()
    await expect(page.getByText(EDIT_DATA.printer, { exact: true })).toBeVisible()
    await expect(page.getByText(`${EDIT_DATA.bedTemp}°C`, { exact: true })).toBeVisible()
    await expect(page.getByText(`${EDIT_DATA.nozzleTemp}°C`, { exact: true })).toBeVisible()
    await expect(statusBadge(page, 'Completed')).toBeVisible()
  })

  test('should show immutable warning for failed runs', async ({ page }) => {
    await createProductionRun(page)

    // Open the Cancel / Fail dialog and switch to "Mark as Failed"
    await page.getByRole('button', { name: 'Cancel / Fail' }).click()
    const failDialog = page.getByRole('dialog')
    await expect(failDialog.getByText('Cancel Production Run')).toBeVisible()
    await failDialog.getByRole('radio', { name: 'Mark as Failed' }).click()
    await expect(failDialog.getByText('Mark Run as Failed')).toBeVisible()

    // A failure needs a reason and the filament wasted
    await failDialog.getByRole('combobox', { name: /Failure Reason/ }).click()
    await page.getByRole('option').first().click()
    await failDialog.getByRole('spinbutton').first().fill('5')
    await failDialog.getByRole('button', { name: 'Mark as Failed' }).click()
    await expect(failDialog).toBeHidden({ timeout: 30000 })

    await expect(statusBadge(page, 'Failed')).toBeVisible()

    // Edit: lock alert for failed status, tabs hidden
    const dialog = await openEditDialog(page)
    await expect(dialog.getByText(/This run is failed\. Only notes can be edited\./)).toBeVisible()
    await expect(dialog.getByRole('tab', { name: 'Basic Info' })).toHaveCount(0)
  })

  test('should show immutable warning for cancelled runs', async ({ page }) => {
    await createProductionRun(page)

    // Cancel with the default full reversal
    await page.getByRole('button', { name: 'Cancel / Fail' }).click()
    const cancelDialog = page.getByRole('dialog')
    await expect(cancelDialog.getByText('Cancel Production Run')).toBeVisible()
    await cancelDialog.getByRole('button', { name: 'Cancel Run', exact: true }).click()
    await expect(cancelDialog).toBeHidden({ timeout: 30000 })

    await expect(statusBadge(page, 'Cancelled')).toBeVisible()

    // Edit: lock alert for cancelled status
    const dialog = await openEditDialog(page)
    await expect(dialog.getByText(/This run is cancelled\. Only notes can be edited\./)).toBeVisible()
    await expect(dialog.getByRole('tab', { name: 'Basic Info' })).toHaveCount(0)
  })
})
