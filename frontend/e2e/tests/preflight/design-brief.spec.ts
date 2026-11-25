/**
 * Preflight foundations end to end (spec 009, T058): a design brief on an
 * idea, a printer calibration, and a test result on a model.
 *
 * Runs as the disposable account of `../../fixtures` (created through the
 * local API); every name is unique per run. Needs the backend — a skip here
 * is not a pass.
 */
import { type Page } from '@playwright/test'

import { test, expect } from '../../fixtures'
import { API_URL } from '../../config'
import { apiAs, isBackendAvailable, openDashboard, uniqueSuffix } from '../../helpers'

const STL = `solid block
facet normal 0 0 1
outer loop
vertex 0 0 10
vertex 10 0 10
vertex 0 10 10
endloop
endfacet
endsolid block
`

async function uploadVersion(page: Page, modelId: string): Promise<void> {
  const stored = await page.evaluate(
    () => localStorage.getItem('batchivo_auth_tokens') ?? sessionStorage.getItem('batchivo_auth_tokens')
  )
  const { accessToken } = JSON.parse(stored ?? '{}') as { accessToken: string }
  const response = await page.request.post(`${API_URL}/api/v1/models/${modelId}/files`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    multipart: {
      file: { name: 'hook.stl', mimeType: 'application/octet-stream', buffer: Buffer.from(STL) },
      file_type: 'source_stl',
    },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

test.describe('Preflight foundations', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    await openDashboard(page)
  })

  test('start a brief on an idea, edit its intent, set a step, see the history', async ({ page }) => {
    const api = await apiAs(page)
    const idea = await api.post('/api/v1/ideas', { title: `Porte-sac ${uniqueSuffix()}` })
    await page.goto(`/ideas/${idea.id}`)
    await page.getByRole('tab', { name: 'Design brief' }).click()
    await page.getByRole('button', { name: 'Start a design brief' }).click()

    await page.getByRole('button', { name: 'Edit intent' }).click()
    await page.getByLabel('Function').fill('Tient un sac de courses')
    await page.getByLabel('loads (YAML or JSON)').fill(
      '- value: 5\n  unit: kg\n  direction: vers le bas\n  duration: cyclic\n  status: validé'
    )
    await page.getByRole('button', { name: 'Save intent' }).click()
    await expect(page.getByText('Tient un sac de courses')).toBeVisible()
    await expect(page.getByText('validé')).toBeVisible()

    // An enum Preflight does not know is refused, and the error names the field.
    await page.getByRole('button', { name: 'Edit intent' }).click()
    await page.getByLabel('loads (YAML or JSON)').fill('- value: 5\n  duration: forever')
    await page.getByRole('button', { name: 'Save intent' }).click()
    await expect(page.getByRole('alert')).toContainText('duration')
    await page.getByRole('button', { name: 'Cancel' }).click()

    await page.getByLabel('Risk status').selectOption('done')
    await expect(page.getByLabel('Risk status')).toHaveValue('done')

    await page.getByRole('button', { name: /History \(1\)/ }).click()
    const history = page.getByRole('dialog')
    await expect(history.getByRole('button', { name: /Intent/ })).toBeVisible()
  })

  test('record a calibration on a printer, then supersede it', async ({ page }) => {
    const api = await apiAs(page)
    const name = `Calib printer ${uniqueSuffix()}`
    await api.post('/api/v1/printers', { name, manufacturer: 'Bambu Lab', model: 'A1' })
    await page.goto('/printers')
    await page.getByLabel(`Calibrations for ${name}`).first().click()

    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Clearance per side (mm)').fill('0.15')
    await dialog.getByRole('button', { name: 'Record value' }).click()
    await expect(dialog.getByText('0.150 mm')).toBeVisible()

    await dialog.getByLabel('Clearance per side (mm)').fill('0.175')
    await dialog.getByRole('button', { name: 'Record value' }).click()
    await expect(dialog.getByText('0.175 mm')).toBeVisible()
    await dialog.getByRole('button', { name: 'History (1)' }).click()
    await expect(dialog.getByText('0.150 mm')).toBeVisible()
  })

  test('record a failed test print on a model version', async ({ page }) => {
    const api = await apiAs(page)
    const model = await api.post('/api/v1/models', {
      sku: `PF-${uniqueSuffix()}`.slice(0, 40),
      name: `Hook ${uniqueSuffix()}`,
    })
    await uploadVersion(page, model.id)
    await page.goto(`/models/${model.id}`)

    await expect(page.getByText('No test print recorded yet')).toBeVisible()
    await page.getByRole('button', { name: 'Record a test' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Outcome').selectOption('fail')
    await dialog.getByLabel('Measurement 1 name').fill('load_kg')
    await dialog.getByLabel('Measurement 1 value').fill('7')
    await dialog.getByLabel('Failure mode').fill('broke at the root at 7 kg')
    await dialog.getByRole('button', { name: 'Record result' }).click()

    await expect(page.getByText('Failure: broke at the root at 7 kg')).toBeVisible()
    await expect(page.getByRole('status').filter({ hasText: 'Last test: Fail' })).toBeVisible()
  })
})
