/**
 * A price has a history, and a quantity can have its own price (T266, US5).
 *
 * The history shows the period each price applied for; adding a 10+ tier on
 * the same channel lists it beside the base price rather than replacing it.
 */

import { expect, test } from '@playwright/test'

import { E2E_CHANNEL } from '../config'
import { OWNER_STATE, openProduct } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

test('the history shows the current price and its period', async ({ page }) => {
  await openProduct(page)
  await page.getByRole('button', { name: `Price history for ${E2E_CHANNEL}` }).click()

  const dialog = page.getByRole('dialog', { name: 'Price history' })
  await expect(dialog.getByText('Current')).toBeVisible()
  await expect(dialog.getByText('£34.99')).toBeVisible()
})

test('a quantity tier is priced beside the base price', async ({ page }) => {
  await openProduct(page)
  await page.getByRole('button', { name: 'Add Pricing' }).click()

  const dialog = page.getByRole('dialog', { name: 'Add Channel Pricing' })
  await dialog.getByRole('combobox').first().click()
  await page.getByRole('option', { name: new RegExp(E2E_CHANNEL) }).click()
  await dialog.getByLabel(/List Price/).fill('31.00')
  await dialog.getByLabel('Applies from quantity').fill('10')
  await dialog.getByRole('button', { name: 'Add Pricing' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByRole('cell', { name: '10+', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '1+', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '£31.00' })).toBeVisible()
})
