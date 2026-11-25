/**
 * Helpers for the pricing journeys (T266).
 *
 * Every journey runs against the tenant `backend/scripts/seed_e2e.py` seeds,
 * signed in as its owner or its viewer -- never the production account
 * (Constitution II).
 */

import { expect, type Page } from '@playwright/test'

import {
  E2E_CHANNEL,
  E2E_OWNER_EMAIL,
  E2E_PASSWORD,
  E2E_PRODUCT,
  E2E_VIEWER_EMAIL,
} from '../config'

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('you@example.com').fill(email)
  await page.locator('input[type="password"]').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL('**/dashboard')
}

export const signInAsOwner = (page: Page) => signIn(page, E2E_OWNER_EMAIL)
export const signInAsViewer = (page: Page) => signIn(page, E2E_VIEWER_EMAIL)

/** Where `auth.setup.ts` saves each role's signed-in session. */
export const OWNER_STATE = 'e2e/.auth/pricing-owner.json'
export const VIEWER_STATE = 'e2e/.auth/pricing-viewer.json'

/** Open the seeded product's page from the product list. */
export async function openProduct(page: Page): Promise<void> {
  await page.goto('/products')
  await page.getByRole('link', { name: E2E_PRODUCT }).first().click()
  await expect(page.getByRole('heading', { name: E2E_PRODUCT })).toBeVisible()
}

/** Open the seeded channel's page from the channel list. */
export async function openChannel(page: Page): Promise<void> {
  await page.goto('/sales-channels')
  await page.getByRole('link', { name: E2E_CHANNEL }).first().click()
  await expect(page.getByTestId('fee-rule-editor')).toBeVisible()
}

/** The pricing tab of the settings page. */
export async function openPricingSettings(page: Page): Promise<void> {
  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Pricing' }).click()
  await expect(page.getByTestId('pricing-policy-settings')).toBeVisible()
}

/**
 * The seeded channel's base (1+) price row. The tier journey adds a 10+ row on
 * the same channel, so anything aimed at "the channel's price" names the base.
 */
export function baseChannelRow(page: Page) {
  return page.getByRole('row').filter({ hasText: E2E_CHANNEL }).filter({ hasText: '1+' })
}
