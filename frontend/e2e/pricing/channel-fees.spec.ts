/**
 * What a channel charges, and what it actually charged (T266).
 *
 * US3: the channel's fee rules are listed and an order's fees can be tried
 * without saving anything. FR-041a-d: a fee from a statement is recorded as
 * the operator's figure and set against what the rules planned.
 */

import { expect, test } from '@playwright/test'

import { OWNER_STATE, openChannel } from './pricing-helpers'

test.use({ storageState: OWNER_STATE })

test.beforeEach(async ({ page }) => {
  await openChannel(page)
})

test('lists the fee rules with what each is charged on', async ({ page }) => {
  const editor = page.getByTestId('fee-rule-editor')
  await expect(editor.getByTestId('fee-rule-transaction')).toContainText('Item + shipping')
  await expect(editor.getByTestId('fee-rule-payment_processing')).toContainText('Order total')
  await expect(editor.getByTestId('fee-rule-listing')).toContainText('Per listing')
})

test('previews the fees on an order without saving anything', async ({ page }) => {
  const preview = page.getByTestId('fee-preview-panel')
  await preview.getByLabel('Item price').fill('34.99')
  await preview.getByRole('button', { name: /Preview fees/ }).click()

  const result = preview.getByTestId('fee-preview-result')
  await expect(result).toBeVisible()
  await expect(result).toContainText('transaction')
})

test('a fee from a statement is recorded and reconciled against the plan', async ({ page }) => {
  const form = page.getByTestId('fee-actual-form')
  await form.getByLabel('Fee category').fill('transaction')
  await form.getByLabel(/Amount/).fill('2.27')
  await form.getByRole('button', { name: /Record fee/ }).click()

  await expect(form.getByTestId('fee-actual-recorded')).toBeVisible()
  await expect(page.getByTestId('reconcile-actual-transaction')).toContainText('2.27')
})
