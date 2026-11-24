/**
 * E2E Test Helpers
 *
 * Shared helper functions for E2E tests including authentication
 * with retry logic for rate limiting.
 */

import { Page } from '@playwright/test'
import { API_URL, HEALTH_URL } from './config'

/**
 * Check if the backend API is available
 */
export async function isBackendAvailable(): Promise<boolean> {
  try {
    const response = await fetch(HEALTH_URL)
    return response.ok
  } catch {
    return false
  }
}

/**
 * Read the pending email-verification token for a registration.
 *
 * Uses the backend's e2e-only hook, which answers 404 unless the backend runs
 * with E2E_TEST_HOOKS_ENABLED=true (never in production).
 */
async function fetchVerificationToken(page: Page, email: string): Promise<string> {
  const response = await page.request.get(
    `${API_URL}/api/v1/onboarding/test/verification-token`,
    { params: { email } }
  )
  if (response.status() === 404) {
    throw new Error(
      'No verification token from the e2e hook. Start the local backend with ' +
        'E2E_TEST_HOOKS_ENABLED=true (see e2e/README.md).'
    )
  }
  if (!response.ok()) {
    throw new Error(`Verification token hook failed: HTTP ${response.status()}`)
  }
  const body = (await response.json()) as { token: string }
  return body.token
}

/**
 * Register a new user and login
 *
 * Creates a unique tenant + owner for test isolation by walking the real
 * signup flow: fill /signup (business name included), read the verification
 * token through the backend's e2e hook, open /verify-email?token=… (the real
 * verification, which stores the session), then land on /dashboard.
 *
 * Includes retry logic with exponential backoff for the 5/minute rate limit
 * on POST /onboarding/register.
 *
 * @param page - Playwright page object
 * @param maxRetries - Maximum number of retry attempts (default: 3)
 * @returns The email of the created user
 */
export async function registerAndLogin(page: Page, maxRetries: number = 3): Promise<string> {
  const testPassword = 'TestPassword123!'

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const suffix = `${Date.now()}-${Math.random().toString(36).substring(7)}`
    const testEmail = `test-${suffix}@example.com`

    await page.goto('/signup')
    await page.fill('#businessName', `E2E Shop ${suffix}`)
    await page.fill('#email', testEmail)
    await page.fill('#password', testPassword)
    await page.fill('#confirmPassword', testPassword)

    const registerResponse = page.waitForResponse(
      (r) => r.url().includes('/onboarding/register') && r.request().method() === 'POST',
      { timeout: 15000 }
    )
    await page.click('button[type="submit"]')
    const status = (await registerResponse).status()

    if (status === 429 && attempt < maxRetries) {
      // Rate limit is 5/minute: back off 5s, 10s, 20s (max 30s)
      const waitTime = Math.min(5000 * Math.pow(2, attempt), 30000)
      console.log(`Rate limited. Waiting ${waitTime / 1000}s before retry ${attempt + 1}/${maxRetries}`)
      await page.waitForTimeout(waitTime)
      continue
    }
    if (status !== 201) {
      throw new Error(`Registration failed: POST /onboarding/register answered HTTP ${status}`)
    }

    await page.getByText('Check your email').waitFor({ timeout: 10000 })

    // Real verification: the page calls POST /verify-email and stores the JWTs.
    const token = await fetchVerificationToken(page, testEmail)
    await page.goto(`/verify-email?token=${encodeURIComponent(token)}`)
    const storedTokens = await page.waitForFunction(
      () =>
        localStorage.getItem('batchivo_auth_tokens') ??
        sessionStorage.getItem('batchivo_auth_tokens'),
      undefined,
      { timeout: 15000 }
    )
    const { accessToken } = JSON.parse((await storedTokens.jsonValue()) as string) as {
      accessToken: string
    }

    // A new signup is a "generic" business until setup step 2 picks the craft,
    // which decides the modules. Pick 3D printing through that real wizard step,
    // as the owner would, so the 3D-print screens (models, printers, …) exist.
    const craft = await page.request.put(`${API_URL}/api/v1/onboarding/wizard/step/2`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      data: { tenant_type: 'three_d_print' },
    })
    if (!craft.ok()) {
      throw new Error(`Setting the business type failed: HTTP ${craft.status()}`)
    }

    await page.goto('/dashboard')
    await page.waitForURL('/dashboard', { timeout: 15000 })
    return testEmail
  }

  throw new Error(`Registration failed after ${maxRetries} retries. Rate limit may be exceeded.`)
}

/**
 * Create a test user and return credentials (for login tests)
 *
 * Registers a user, then logs out so the login flow can be tested.
 *
 * @param page - Playwright page object
 * @returns Object with email and password
 */
export async function createTestUser(page: Page): Promise<{ email: string; password: string }> {
  const email = await registerAndLogin(page)
  const password = 'TestPassword123!'

  // Logout to test login flow
  await page.goto('/logout')
  await page.waitForURL('/login', { timeout: 10000 })

  return { email, password }
}

/**
 * Wait for page to be fully loaded and stable
 */
export async function waitForPageStable(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle')
}

/**
 * Click element and verify navigation
 */
export async function clickAndNavigate(
  page: Page,
  selector: string,
  expectedUrl: RegExp,
  timeout: number = 10000
): Promise<void> {
  await page.click(selector)
  await page.waitForURL(expectedUrl, { timeout })
  await waitForPageStable(page)
}
