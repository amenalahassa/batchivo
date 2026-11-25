/**
 * Ideas end to end (spec 007, T052): capture, iterate, convert, import.
 *
 * Signs in as the owner of the e2e tenant `backend/scripts/seed_e2e.py` seeds
 * (the owner may convert to a product). `registerAndLogin` cannot be used:
 * signup now waits for an emailed verification link (bug
 * e2e-register-verification). Titles and links are unique per run,
 * so the spec can run again on the same database. Needs the backend on 8000 —
 * a skip here is not a pass.
 */
import { test, expect, type Page } from '@playwright/test'

import { isBackendAvailable } from '../../helpers'
import { signInAsOwner } from '../../pricing/pricing-helpers'

// A real 1x1 PNG, so the server can make its thumbnail.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64'
)

function unique(label: string): string {
  return `${label} ${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
}

async function createIdea(page: Page, title: string) {
  await page.goto('/ideas')
  await page.getByRole('button', { name: 'New idea' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Title').fill(title)
  for (const [label, value] of [
    ['Frequency', '4'],
    ['Frustration', '4'],
    ['Printability', '4'],
    ['Gap', '3'],
    ['Willingness to pay', '3'],
  ]) {
    await dialog.getByLabel(label, { exact: true }).selectOption(value)
  }
  await dialog.getByRole('button', { name: 'Create' }).click()
  await page.waitForURL(/\/ideas\/[a-f0-9-]+$/, { timeout: 15000 })
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
}

test.describe('Ideas', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    await signInAsOwner(page)
  })

  test('capture an idea, iterate on it and convert it to a product', async ({ page }) => {
    const title = unique('Visor clip')
    await createIdea(page, title)
    await expect(page.getByText('18/25')).toBeVisible()

    // Timeline: a note, two images, a second iteration.
    await page.getByLabel('Entry text').fill('Clip must hold **two** cards')
    await page.getByRole('button', { name: 'Add note' }).click()
    await expect(page.getByText('two', { exact: true })).toBeVisible()

    await page.getByLabel('Image files').setInputFiles([
      { name: 'front.png', mimeType: 'image/png', buffer: PNG },
      { name: 'side.png', mimeType: 'image/png', buffer: PNG },
    ])
    await expect(page.getByRole('button', { name: 'Open front.png' })).toBeVisible({
      timeout: 15000,
    })
    await expect(page.getByRole('button', { name: 'Open side.png' })).toBeVisible()

    await page.getByRole('button', { name: 'Start next iteration' }).click()
    await page.getByLabel('Note (optional)').fill('Thicker arm')
    await page.getByRole('button', { name: 'Start iteration' }).click()
    await expect(page.getByRole('heading', { name: 'Iteration 2' })).toBeVisible()

    // Cover, then pin the other image so the product gets both.
    const front = page.getByRole('listitem', { name: 'Image entry' }).filter({
      has: page.getByRole('button', { name: 'Open front.png' }),
    })
    await front.getByRole('button', { name: 'Set as cover' }).click()
    await expect(front.getByText('Cover', { exact: true })).toBeVisible()

    // The board card carries the score and the cover.
    await page.goto('/ideas')
    const card = page.getByRole('article', { name: title })
    await expect(card.getByText('18/25')).toBeVisible()
    await expect(card.getByRole('img', { name: title })).toBeVisible({ timeout: 15000 })

    // Convert to a product.
    await card.getByRole('link', { name: title }).click()
    await page.getByRole('button', { name: 'Convert to product' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Product reference')).not.toHaveValue('', { timeout: 10000 })
    await dialog.getByRole('button', { name: 'Convert' }).click()
    await dialog.getByRole('link', { name: 'Open the product' }).click()

    await page.waitForURL(/\/products\/[a-f0-9-]+$/, { timeout: 15000 })
    // The product's own model line links by the same name; the idea link sits in "From idea".
    const fromIdea = page.locator('p', { hasText: 'From idea:' })
    await expect(fromIdea.getByRole('link', { name: title })).toBeVisible()
  })

  test('import a pain-point report, then the same report again', async ({ page }) => {
    const id = Date.now()
    const report = [
      '## Top 10',
      `### 1. Hose guide ${id} — 19/25`,
      '- Niche : garden',
      `- Preuves : [Forum](https://forum.example.org/${id}/1)`,
      '- Idée produit : clip-on hose guide',
      `### 2. Cable tidy ${id} — 17/25`,
      '- Niche : desk',
      `- Preuves : [Forum](https://forum.example.org/${id}/2)`,
    ].join('\n')

    await page.goto('/ideas')
    await page.getByRole('button', { name: 'Import report' }).first().click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Report', { exact: true }).fill(report)
    await dialog.getByRole('button', { name: 'Preview' }).click()
    await expect(dialog.getByText('2 to create · 0 already imported · 0 refused')).toBeVisible({
      timeout: 15000,
    })
    await dialog.getByRole('button', { name: 'Import 2 ideas' }).click()
    await expect(dialog.getByText('2 created · 0 skipped · 0 refused')).toBeVisible()
    await dialog.getByRole('button', { name: 'Close' }).first().click()

    const inbox = page.getByRole('region', { name: 'Inbox' })
    await expect(
      inbox.getByRole('article', { name: `Hose guide ${id}` }).getByText('Report score 19/25')
    ).toBeVisible()

    await page.getByRole('button', { name: 'Import report' }).first().click()
    await dialog.getByLabel('Report', { exact: true }).fill(report)
    await dialog.getByRole('button', { name: 'Preview' }).click()
    await expect(dialog.getByText('0 to create · 2 already imported · 0 refused')).toBeVisible({
      timeout: 15000,
    })
  })
})
