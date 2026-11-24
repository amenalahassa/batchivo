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
export async function fetchVerificationToken(page: Page, email: string): Promise<string> {
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
    // Poll from Node until the page has stored the session. Not waitForFunction():
    // the page loads zone.js, and on WebKit that turns the predicate's result into
    // a (truthy) promise object, so the wait returns before anything is stored.
    const accessToken = await pollAccessToken(page, 15000)

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

/**
 * Read the signed-in user's access token from browser storage.
 */
export async function getAccessToken(page: Page): Promise<string> {
  const token = await readAccessToken(page)
  if (!token) throw new Error('No stored session: call registerAndLogin first')
  return token
}

async function readAccessToken(page: Page): Promise<string | null> {
  const raw = await page.evaluate(
    () =>
      localStorage.getItem('batchivo_auth_tokens') ??
      sessionStorage.getItem('batchivo_auth_tokens')
  )
  return typeof raw === 'string' ? (JSON.parse(raw) as { accessToken: string }).accessToken : null
}

async function pollAccessToken(page: Page, timeout: number): Promise<string> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const token = await readAccessToken(page).catch(() => null) // navigation in flight
    if (token) return token
    await page.waitForTimeout(200)
  }
  throw new Error(`No stored session ${timeout / 1000}s after opening the verification link`)
}

/**
 * Authorized JSON API calls as the signed-in user, for seeding test data that
 * a spec needs but does not test (a product to attach a category to, …).
 */
export async function apiAs(page: Page) {
  const headers = { Authorization: `Bearer ${await getAccessToken(page)}` }
  async function call<T>(method: 'get' | 'post' | 'put' | 'patch' | 'delete', path: string, data?: unknown): Promise<T> {
    const response = await page.request[method](`${API_URL}${path}`, { headers, data })
    if (!response.ok()) {
      throw new Error(`${method.toUpperCase()} ${path} answered HTTP ${response.status()}: ${await response.text()}`)
    }
    return (response.status() === 204 ? undefined : await response.json()) as T
  }
  // Responses are untyped JSON: specs read the few fields they assert on.
  /* eslint-disable @typescript-eslint/no-explicit-any */
  return {
    get: <T = any>(path: string) => call<T>('get', path),
    post: <T = any>(path: string, data?: unknown) => call<T>('post', path, data ?? {}),
    put: <T = any>(path: string, data?: unknown) => call<T>('put', path, data ?? {}),
    patch: <T = any>(path: string, data?: unknown) => call<T>('patch', path, data ?? {}),
    delete: <T = any>(path: string) => call<T>('delete', path),
  }
  /* eslint-enable @typescript-eslint/no-explicit-any */
}

/** A unique suffix for test data names. */
export function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`
}
