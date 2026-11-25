/**
 * Generative AI end to end (spec 008, T049).
 *
 * Never reaches Replicate: the backend runs with E2E_TEST_HOOKS_ENABLED=true,
 * GENAI_PROVIDER_BASE_URL pointing at its own fake provider
 * (`/api/v1/genai/e2e-fake`) and GENAI_RUN_INLINE=true. The token typed below
 * is a fake. Each test opens signed in as the owner of a fresh shop (the
 * `fixtures` default; the owner may change the AI settings). A skip here is
 * not a pass.
 */
import { type Page } from '@playwright/test'

import { API_URL } from '../../config'
import { test, expect } from '../../fixtures'
import { isBackendAvailable } from '../../helpers'

const FAKE_TOKEN = 'r8_e2eFakeTokenNotReal000000000000000'

// A real PNG, so the server can make its thumbnail.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64'
)

async function fakeProviderIsOn(): Promise<boolean> {
  try {
    // Hooks on is not enough: the backend's jobs must go to the fake, never to Replicate.
    const response = await fetch(`${API_URL}/api/v1/genai/e2e-fake/status`)
    if (!response.ok) return false
    return ((await response.json()) as { provider_is_fake: boolean }).provider_is_fake
  } catch {
    return false
  }
}

async function accessToken(page: Page): Promise<string> {
  const raw = await page.evaluate(
    () =>
      localStorage.getItem('batchivo_auth_tokens') ?? sessionStorage.getItem('batchivo_auth_tokens')
  )
  return (JSON.parse(raw as string) as { accessToken: string }).accessToken
}

async function connectReplicate(page: Page) {
  await page.goto('/settings?tab=ai')
  await page.getByRole('tab', { name: 'AI' }).click()
  await page.getByLabel('Your Replicate token').fill(FAKE_TOKEN)
  await page.getByRole('button', { name: 'Save token' }).click()
  await expect(page.getByText('Saved token:')).toBeVisible()
  await expect(page.getByText(FAKE_TOKEN)).toHaveCount(0)
}

async function createIdea(page: Page, title: string): Promise<string> {
  const token = await accessToken(page)
  const response = await page.request.post(`${API_URL}/api/v1/ideas`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { title, summary: 'Holds two cards on the visor' },
  })
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { id: string }).id
}

test.describe('Generative AI', () => {
  // A generation waits on the backend's real poll cycle (2 s, then 3 s), on top of the
  // sign-in and setup, which take longer while other workers run beside it.
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    test.skip(
      !(await fakeProviderIsOn()),
      'Fake provider not in use (E2E hooks off, or GENAI_PROVIDER_BASE_URL not the fake)'
    )
    // Load the app so the signed-in session is in this page's storage.
    await page.goto('/')
  })

  test('connect Replicate, test it and set a budget', async ({ page }) => {
    await connectReplicate(page)
    await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByText(/Connected as/)).toBeVisible()
    await page.getByLabel('Monthly budget (USD)').fill('12.50')
    await page.getByRole('button', { name: 'Save budget' }).click()
    await expect(page.getByLabel('Monthly budget (USD)')).toHaveValue('12.50')
  })

  test('generate a concept on an idea and adopt it into the timeline', async ({ page }) => {
    await connectReplicate(page)
    const ideaId = await createIdea(page, `Visor clip ${Date.now()}`)
    await page.goto(`/ideas/${ideaId}`)
    await page.getByRole('button', { name: 'Generate concept' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Describe the concept')).toHaveValue(/Visor clip/)
    await expect(dialog.getByText(/Estimated cost: \$0\.0030 USD/)).toBeVisible()
    await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
    await expect(dialog.getByRole('status')).toHaveText('Done', {
      timeout: 30000,
    })
    await dialog.getByRole('button', { name: 'Add to idea' }).first().click()
    await expect(dialog.getByRole('button', { name: 'Added' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByLabel('AI: made with generative AI').first()).toBeVisible()
  })

  test('a budget of zero refuses the generation before any provider call', async ({ page }) => {
    await connectReplicate(page)
    await page.getByLabel('Monthly budget (USD)').fill('0')
    const saved = page.waitForResponse(
      (r) => r.url().includes('/settings/replicate') && r.request().method() === 'PUT'
    )
    await page.getByRole('button', { name: 'Save budget' }).click()
    expect(((await (await saved).json()) as { monthly_budget: string }).monthly_budget).toBe('0.00')
    const ideaId = await createIdea(page, `Budget idea ${Date.now()}`)
    await page.goto(`/ideas/${ideaId}`)
    await page.getByRole('button', { name: 'Generate concept' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
    await expect(dialog.getByText(/over the monthly budget/)).toBeVisible()
  })

  test('remove the background of a product photo and adopt it with the AI badge', async ({
    page,
  }) => {
    await connectReplicate(page)
    const token = await accessToken(page)
    const headers = { Authorization: `Bearer ${token}` }
    const product = await page.request.post(`${API_URL}/api/v1/products`, {
      headers,
      data: { sku: `E2E-AI-${Date.now()}`, name: 'AI photo product' },
    })
    expect(product.ok()).toBeTruthy()
    const productId = ((await product.json()) as { id: string }).id
    const upload = await page.request.post(`${API_URL}/api/v1/products/${productId}/images`, {
      headers,
      multipart: {
        file: { name: 'front.png', mimeType: 'image/png', buffer: PNG },
      },
    })
    expect(upload.ok()).toBeTruthy()

    await page.goto(`/products/${productId}`)
    await page
      .getByRole('button', { name: /^AI actions/ })
      .first()
      .click()
    await page.getByRole('menuitem', { name: 'Remove background' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Generate', exact: true }).click()
    await expect(dialog.getByRole('status')).toHaveText('Done', {
      timeout: 30000,
    })
    await dialog.getByRole('button', { name: 'Add to product' }).first().click()
    await expect(dialog.getByRole('button', { name: 'Added' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByLabel('AI: made with generative AI').first()).toBeVisible()
  })
})
