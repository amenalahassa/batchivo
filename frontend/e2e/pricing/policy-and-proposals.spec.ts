/**
 * The pricing policy, and the estimates telemetry proposes (T266).
 *
 * FR-007a/c/d: the policy's levers each say where their figure came from, an
 * administrator changes one lever without relabelling the rest (T260), and a
 * viewer reads the policy but cannot change it. US6/AC6c: an observation that
 * disagrees with an estimate waits to be accepted or rejected.
 */

import { expect, test } from '@playwright/test'

import { OWNER_STATE, VIEWER_STATE, openPricingSettings } from './pricing-helpers'

test.describe('as the owner', () => {
  test.use({ storageState: OWNER_STATE })

  test('changing one lever marks that lever decided and leaves the rest as they were', async ({
    page,
  }) => {
    await openPricingSettings(page)
    const settings = page.getByTestId('pricing-policy-settings')
    const electricity = settings.getByLabel(/Electricity rate \(per kWh\)/)

    await expect(settings.locator('label', { hasText: 'Electricity rate' })).toContainText(
      /Assumed/,
    )
    await electricity.fill('0.2500')
    await settings.getByRole('button', { name: /Save pricing policy/ }).click()

    await expect(settings.locator('label', { hasText: 'Electricity rate' })).toContainText(
      /Your setting/,
    )
    // The margin basis was not touched and is still nobody's decision.
    await expect(
      settings.locator('label', { hasText: 'What a margin percentage is taken over' }),
    ).toContainText(/Assumed/)
  })

  test('a held observation is accepted, and another rejected', async ({ page }) => {
    await openPricingSettings(page)
    const proposals = page.getByTestId('estimate-proposals')
    await expect(proposals.getByTestId('proposal-count')).toHaveText('2')
    await expect(proposals.getByTestId('proposal-confidence').first()).toContainText('confidence')

    await proposals.getByRole('button', { name: /^Accept the observed/ }).first().click()
    await expect(proposals.getByTestId('proposal-count')).toHaveText('1')

    await proposals.getByRole('button', { name: /^Reject the observed/ }).first().click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Keep the current figure' }).click()
    await expect(proposals.getByTestId('no-proposals')).toBeVisible()
  })
})

test.describe('as a viewer', () => {
  test.use({ storageState: VIEWER_STATE })

  test('reads the policy but every control is disabled', async ({ page }) => {
    await openPricingSettings(page)
    const settings = page.getByTestId('pricing-policy-settings')

    await expect(settings.getByLabel(/Print handling rate/)).toBeDisabled()
    await expect(settings.getByLabel(/Electricity rate/)).toBeDisabled()
    await expect(settings.getByRole('button', { name: /Save pricing policy/ })).toHaveCount(0)
  })
})
