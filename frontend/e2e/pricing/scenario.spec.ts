/**
 * A catalogue scenario runs through to its result and writes nothing (T266,
 * US7/AC2).
 *
 * The run is queued for a worker; the screen follows it to a finished state
 * and reports how many products it evaluated and which fall below the floor.
 */

import { expect, test } from '@playwright/test'

import { OWNER_STATE, openProduct } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

test('a material shock runs to a result and leaves every price as it was', async ({ page }) => {
  await page.goto('/scenarios')
  const panel = page.getByTestId('scenario-panel')
  await panel.getByLabel('Material cost change').fill('25')
  await panel.getByLabel('Margin floor').fill('30')
  await panel.getByRole('button', { name: 'Run the scenario' }).click()

  const run = page.getByTestId('scenario-run')
  await expect(run.locator('[data-testid^="scenario-state-"]')).toHaveAttribute(
    'data-testid',
    /scenario-state-(succeeded|partial)/,
    { timeout: 60_000 },
  )
  await expect(run.getByTestId('scenario-evaluated')).toBeVisible()

  // A scenario writes nothing: the product still costs and sells as before.
  await openProduct(page)
  await expect(page.getByRole('cell', { name: '£34.99' }).first()).toBeVisible()
})
