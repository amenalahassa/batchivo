/**
 * Finding a price is a proposal, never a publication (T266).
 *
 * US4/AC1: a target margin returns the price that earns it. US4/AC4: a ladder
 * shows the margin across a range of prices. US4/AC5: neither writes a price
 * -- the row keeps its price until somebody chooses to change it.
 */

import { expect, test } from '@playwright/test'

import { E2E_CHANNEL } from '../config'
import { OWNER_STATE, baseChannelRow, openProduct } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

test.beforeEach(async ({ page }) => {
  await openProduct(page)
  await baseChannelRow(page).getByRole('button', { name: `Find a price for ${E2E_CHANNEL}` }).click()
})

test('solves for a target margin and labels the answer a proposal', async ({ page }) => {
  await page.getByTestId('target-margin-input').fill('40')
  await page.getByTestId('solve-button').click()

  await expect(page.getByTestId('solve-result')).toBeVisible()
  await expect(page.getByTestId('proposed-price')).toContainText('£')
  await expect(page.getByTestId('proposal-badge')).toBeVisible()
  await expect(page.getByTestId('achieved-margin')).toBeVisible()
})

test('shows the margin across a range of prices', async ({ page }) => {
  await page.getByRole('tab', { name: 'Across a range' }).click()
  await page.getByLabel('From', { exact: true }).fill('20')
  await page.getByLabel('To', { exact: true }).fill('40')
  await page.getByLabel('Step', { exact: true }).fill('5')

  const ladder = page.getByTestId('ladder-table')
  await expect(ladder).toBeVisible()
  await expect(ladder.getByRole('row')).toHaveCount(6) // the header and five rungs
})

test('publishes nothing: the row keeps its price', async ({ page }) => {
  await page.getByTestId('target-margin-input').fill('60')
  await page.getByTestId('solve-button').click()
  await expect(page.getByTestId('solve-result')).toBeVisible()

  await page.keyboard.press('Escape')
  await page.reload()

  await expect(page.getByRole('cell', { name: '£34.99' }).first()).toBeVisible()
})
