/**
 * E2E: send a print to a Bambu Lab printer (spec 011).
 *
 * No printer is ever contacted: the connection points at 127.0.0.1, where no
 * printer listens, so the printer is reported unreachable and nothing is sent.
 * The journey covers what an operator sees: Developer Mode off hides
 * "Send print", declaring it on (US3) shows it, and preparing a sliced file
 * shows the summary (US1) with Start print held back while the printer cannot
 * be reached (US2) — and no print job is created.
 */
import { test, expect, Page } from '@playwright/test'
import { strToU8, zipSync } from 'fflate'
import { API_URL } from '../../config'
import { isBackendAvailable, registerAndLogin } from '../../helpers'

const SLICE_INFO = `<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header><header_item key="X-BBL-Client-Type" value="slicer"/></header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="5700"/>
    <metadata key="weight" value="35.10"/>
    <filament id="1" type="PLA" color="#FF0000" used_m="10" used_g="30.10"/>
    <filament id="3" type="PETG" color="#00FF00FF" used_m="2" used_g="5.00"/>
  </plate>
</config>
`

/** A sliced Bambu project: one plate using filaments 1 and 3. */
function slicedProject(): Buffer {
  const zip = zipSync({
    '3D/3dmodel.model': strToU8('<model/>'),
    'Metadata/slice_info.config': strToU8(SLICE_INFO),
    'Metadata/plate_1.gcode': strToU8('; plate 1\nG28\n'),
  })
  return Buffer.from(zip)
}

async function authHeaders(page: Page): Promise<Record<string, string>> {
  // The session's JWTs, as the app stores them after login or email verification.
  const stored = await page.evaluate(
    () =>
      localStorage.getItem('batchivo_auth_tokens') ?? sessionStorage.getItem('batchivo_auth_tokens')
  )
  if (!stored) throw new Error('not logged in')
  const { accessToken } = JSON.parse(stored) as { accessToken: string }
  return { Authorization: `Bearer ${accessToken}` }
}

async function createBambuPrinter(page: Page): Promise<{ id: string; name: string }> {
  const headers = await authHeaders(page)
  const name = `Send Printer ${Date.now()}`
  const created = await page.request.post(`${API_URL}/api/v1/printers`, {
    headers,
    data: { name, manufacturer: 'Bambu Lab', model: 'X1 Carbon' },
  })
  expect(created.ok()).toBeTruthy()
  const printer = await created.json()
  const connection = await page.request.post(
    `${API_URL}/api/v1/printers/${printer.id}/connection`,
    {
      headers,
      data: {
        connection_type: 'bambu_lan',
        serial_number: '01S00E2E0000001',
        ip_address: '127.0.0.1',
        access_code: '12345678',
        developer_mode: false,
      },
    }
  )
  expect(connection.ok()).toBeTruthy()
  return { id: printer.id, name }
}

test.describe('Send a print to a Bambu printer', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await registerAndLogin(page)
  })

  test('Developer Mode gates Send print; prepare shows the summary', async ({ page }) => {
    test.setTimeout(90_000)
    const printer = await createBambuPrinter(page)
    const { name } = printer
    await page.goto('/printers')

    const connectionButton = page
      .getByLabel(`Connection for ${name}`)
      .filter({ visible: true })
      .first()
    await expect(connectionButton).toBeVisible({ timeout: 15000 })
    await expect(page.getByLabel(`Send print to ${name}`)).toHaveCount(0)

    // US3: declare Developer Mode, read what it costs.
    await connectionButton.click()
    const connectionDialog = page.getByRole('dialog')
    await expect(connectionDialog.getByText(/turns off Bambu cloud access/)).toBeVisible()
    await connectionDialog.getByLabel('Developer Mode is on on this printer').click()
    await connectionDialog.getByRole('button', { name: 'Save' }).click()
    await expect(connectionDialog.getByText('Connection saved.')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(connectionDialog).toBeHidden()

    // US1: upload a sliced file, prepare, read the summary.
    const send = page.getByLabel(`Send print to ${name}`).filter({ visible: true }).first()
    await expect(send).toBeVisible()
    await send.click()
    await expect(page.getByRole('heading', { name: `Send print — ${name}` })).toBeVisible()
    await page.getByLabel('Sliced file (.gcode.3mf)').setInputFiles({
      name: 'dragon.gcode.3mf',
      mimeType: 'application/vnd.ms-package.3dmanufacturing-3dmodel+xml',
      buffer: slicedProject(),
    })
    await expect(page.getByLabel('Plate')).toBeVisible({ timeout: 15000 })
    await page.getByRole('button', { name: 'Prepare' }).click()

    const summary = page.getByTestId('print-send-summary')
    await expect(summary).toBeVisible({ timeout: 30000 })
    await expect(summary.getByText('1 h 35 min')).toBeVisible()
    await expect(summary.getByText('35.10 g')).toBeVisible()
    await expect(summary.getByRole('list', { name: 'Blockers' })).toBeVisible()

    // US2: nothing can start while the printer is unreachable.
    await expect(page.getByRole('button', { name: 'Start print' })).toBeDisabled()

    const sends = await page.request.get(`${API_URL}/api/v1/printers/${printer.id}/prints`, {
      headers: await authHeaders(page),
    })
    expect(sends.ok()).toBeTruthy()
    const body = await sends.json()
    expect(body.items).toHaveLength(1)
    expect(body.items[0].status).toBe('prepared')
    expect(body.items[0].print_job).toBeNull()
    expect(JSON.stringify(body)).not.toContain('12345678')
  })
})
