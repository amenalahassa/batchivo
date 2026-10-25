/**
 * Sign the seeded owner and viewer in once each, for every pricing journey.
 *
 * The login endpoint is rate limited; a sign-in per test would trip it long
 * before the suite finished. The sessions are saved where the specs read them.
 */

import { test as setup } from '@playwright/test'

import { OWNER_STATE, VIEWER_STATE, signInAsOwner, signInAsViewer } from './pricing-helpers'

setup('sign in the owner', async ({ page }) => {
  await signInAsOwner(page)
  await page.context().storageState({ path: OWNER_STATE })
})

setup('sign in the viewer', async ({ page }) => {
  await signInAsViewer(page)
  await page.context().storageState({ path: VIEWER_STATE })
})
