/**
 * The cost behind a product, and what one sale of it earns (T266).
 *
 * US2 and US6/AC1-2: every line of the make-cost names where its figure came
 * from, the share of it that is evidence is stated, and the inputs behind it
 * can be read. US3/AC1, AC3, AC4: a price row's margin itemises its fees, sets
 * postage against shipping charged, and names the basis of its percentage.
 */

import { expect, test } from '@playwright/test'

import { E2E_CHANNEL } from '../config'
import { OWNER_STATE, openProduct } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

test.describe('cost breakdown', () => {
  test.beforeEach(async ({ page }) => {
    await openProduct(page)
  })

  test('itemises the make-cost with each line’s origin and the observed share', async ({
    page,
  }) => {
    await expect(page.getByText('Filament in the part')).toBeVisible()
    await expect(page.getByText('Machine occupancy')).toBeVisible()
    // Every line says where its figure came from.
    await expect(page.locator('[data-testid^="provenance-"]').first()).toBeVisible()
    // And how much of the whole is evidence rather than assumption.
    await expect(page.getByText(/rests on observed or measured figures/)).toBeVisible()
  })

  test('reaches the inputs behind the cost, each with its origin', async ({ page }) => {
    await page.getByText('Where these figures come from').click()

    const inputs = page.getByTestId('provenance-fields')
    await expect(inputs).toBeVisible()
    await expect(inputs.getByText(/figures observed/)).toBeVisible()
  })
})

test.describe('the margin on one price row', () => {
  test('itemises fees, sets postage against shipping, and names its basis', async ({ page }) => {
    await openProduct(page)

    await page.getByRole('button', { name: `Margin breakdown for ${E2E_CHANNEL}` }).click()
    const dialog = page.getByRole('dialog', { name: 'Margin breakdown' })

    await expect(dialog.getByText('transaction')).toBeVisible()
    await expect(dialog.getByText('payment_processing')).toBeVisible()
    await expect(dialog.getByTestId('margin-shipping-net')).toContainText('Shipping margin')
    await expect(dialog.getByTestId('margin-percentage')).toBeVisible()
    await expect(dialog.getByText(/of the customer total|of the total the customer paid/)).toBeVisible()
    await expect(dialog.getByTestId('margin-profit')).toContainText('£')
  })
})
