/**
 * Standard packaging and carrier postage, end to end (spec 006, T060).
 *
 * The seeded owner adds the standard packaging catalogue from the Packaging
 * page, sees a catalogue box listed with its figures marked as defaults,
 * then adds the carrier the shop's currency suggests in Settings → Postage
 * and makes one of its services the default the margins price by.
 *
 * The seeded tenant finished onboarding long ago, so step 5 itself is
 * covered by the component and API tests; this journey covers the same
 * seeding reached from the screens an existing shop uses. Runs with the
 * pricing journeys (CI `--project=pricing`).
 */

import { expect, test } from '@playwright/test'

import { OWNER_STATE } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

test('the standard catalogue is added and listed as defaults', async ({ page }) => {
  await page.goto('/packaging')
  await expect(page.getByRole('heading', { name: 'Packaging' })).toBeVisible()

  await page.getByRole('button', { name: 'Add standard packaging' }).click()
  const dialog = page.getByRole('dialog', { name: 'Add standard packaging' })
  await expect(dialog.getByRole('checkbox').first()).toBeVisible()
  const add = dialog.getByRole('button', { name: /^Add \d+ items?$/ })
  if (await add.isEnabled()) {
    await add.click()
    await expect(dialog).toBeHidden()
  } else {
    // A rerun: everything is already present.
    await dialog.getByRole('button', { name: 'Cancel' }).click()
  }

  const box = page.getByTestId('packaging-row-PKG-BOX-CUBE-150')
  await expect(box).toBeVisible()
  await expect(box.getByText('default').first()).toBeVisible()

  // The Consumables page no longer lists packaging, and says where it went.
  await page.goto('/consumables')
  await expect(page.getByRole('link', { name: 'Packaging page' })).toBeVisible()
  await expect(page.getByText(/^Box cube 150/)).toHaveCount(0)
})

test('the suggested carrier is added and a default service chosen', async ({ page }) => {
  await page.goto('/settings')
  const panel = page.getByTestId('shipping-profiles-panel')
  await panel.scrollIntoViewIfNeeded()
  const section = panel.getByTestId('carrier-section')
  await expect(section).toBeVisible()

  const suggestion = section.getByRole('button', { name: /^Add .+ postage$/ })
  if (await suggestion.isVisible()) {
    await suggestion.click()
  }
  await expect(section.getByTestId('carrier-services')).toBeVisible()
  await expect(panel.getByTestId('seeded-profile').first()).toBeVisible()

  const defaultService = section.getByRole('combobox', { name: 'Default service' })
  await defaultService.click()
  const options = page.getByRole('option')
  // The first option is "Cheapest service that fits"; pick a named service.
  await options.nth(1).click()
  await expect(defaultService).not.toHaveText('Cheapest service that fits')
})
