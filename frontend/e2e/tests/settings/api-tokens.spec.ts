/**
 * E2E: Settings > API tokens (spec 010, US1).
 *
 * Create a read-only token in the UI, see its secret once, use it against the
 * API (accepted where tokens are allowed, refused elsewhere), revoke it, and
 * see it refused afterwards.
 */

import { test, expect } from '../../fixtures'
import { API_URL } from '../../config'
import { isBackendAvailable, uniqueSuffix } from '../../helpers'

test.describe('API tokens', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')
  })

  test('create, use and revoke a personal API token', async ({ page }) => {
    await page.getByRole('tab', { name: /api tokens/i }).click()
    await expect(page.getByText('You have no API tokens yet.')).toBeVisible()

    const name = `E2E agent ${uniqueSuffix()}`
    await page.getByRole('button', { name: /create token/i }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Name').fill(name)
    await expect(dialog.getByRole('checkbox', { name: 'Read' })).toBeChecked()
    await expect(dialog.getByRole('checkbox', { name: 'Print' })).not.toBeChecked()
    await dialog.getByRole('button', { name: 'Create token' }).click()

    const secretField = page.getByLabel('New API token')
    await expect(secretField).toBeVisible()
    const secret = await secretField.inputValue()
    expect(secret).toMatch(/^bvt_[a-z2-7]{8}_/)
    await page.getByRole('button', { name: 'I have stored it' }).click()
    await expect(secretField).toBeHidden()

    const row = page.getByRole('row', { name: new RegExp(name) })
    await expect(row).toBeVisible()
    await expect(row.getByText(secret.slice(0, 12) + '…')).toBeVisible()
    await expect(row.getByText('Never used')).toBeVisible()
    await expect(row.getByText('active')).toBeVisible()
    await expect(page.getByText(secret)).toHaveCount(0)

    const auth = { Authorization: `Bearer ${secret}` }
    const ideas = await page.request.get(`${API_URL}/api/v1/ideas`, { headers: auth })
    expect(ideas.status()).toBe(200)
    const me = await page.request.get(`${API_URL}/api/v1/users/me`, { headers: auth })
    expect(me.status()).toBe(403)
    const write = await page.request.post(`${API_URL}/api/v1/ideas`, {
      headers: auth,
      data: { title: 'Not allowed' },
    })
    expect(write.status()).toBe(403)

    await page.reload()
    await page.getByRole('tab', { name: /api tokens/i }).click()
    const usedRow = page.getByRole('row', { name: new RegExp(name) })
    await expect(usedRow.getByText('Never used')).toHaveCount(0)

    await usedRow.getByRole('button', { name: 'Revoke' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Revoke token' }).click()
    await expect(usedRow.getByText('revoked')).toBeVisible()

    const refused = await page.request.get(`${API_URL}/api/v1/ideas`, { headers: auth })
    expect(refused.status()).toBe(401)
  })
})
