/**
 * E2E Tests: Authentication - Registration Flow
 *
 * Tests the registration functionality including:
 * - Successful registration: signup, "Check your email", verification, dashboard
 * - Form validation errors (password rules, mismatch)
 * - Duplicate email registration
 * - Navigation to key areas on a new account
 *
 * Prerequisites:
 * - Backend started with E2E_TEST_HOOKS_ENABLED=true (see e2e/README.md): the
 *   verification step reads the token through the backend's e2e-only hook.
 */

import { test, expect, type Page } from '@playwright/test'
import { fetchVerificationToken, isBackendAvailable, registerAndLogin } from '../../helpers'

const TEST_PASSWORD = 'TestPassword123!'

// Generate unique test email to avoid conflicts between test runs
function generateTestEmail(): string {
  return `test-${Date.now()}-${Math.random().toString(36).substring(7)}@example.com`
}

/** Fill the signup form. The business name is required by the form. */
async function fillSignup(
  page: Page,
  email: string,
  options: { password?: string; confirmPassword?: string; fullName?: string } = {}
): Promise<void> {
  const password = options.password ?? TEST_PASSWORD
  await page.fill('#businessName', `E2E Shop ${Date.now()}`)
  if (options.fullName) await page.fill('#fullName', options.fullName)
  await page.fill('#email', email)
  await page.fill('#password', password)
  await page.fill('#confirmPassword', options.confirmPassword ?? password)
}

/** Open the verification link for `email`, as the user would from the email. */
async function verifyFromEmail(page: Page, email: string): Promise<void> {
  const token = await fetchVerificationToken(page, email)
  await page.goto(`/verify-email?token=${encodeURIComponent(token)}`)
}

test.describe('Registration Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/signup')
  })

  test('should display registration form with all elements', async ({ page }) => {
    // Verify page title and description
    await expect(page.getByText('Create an account')).toBeVisible()
    await expect(page.getByText('Sign up for Batchivo to get started')).toBeVisible()

    // Verify form elements exist
    await expect(page.locator('#businessName')).toBeVisible()
    await expect(page.locator('#fullName')).toBeVisible()
    await expect(page.locator('#email')).toBeVisible()
    await expect(page.locator('#password')).toBeVisible()
    await expect(page.locator('#confirmPassword')).toBeVisible()
    await expect(page.locator('button[type="submit"]')).toBeVisible()

    // Verify navigation link to login
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()

    // Password requirements appear once the user starts typing a password
    await page.fill('#password', 'a')
    await expect(page.getByText('8+ characters')).toBeVisible()
  })

  test('should successfully register with valid credentials', async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')

    const testEmail = generateTestEmail()
    await fillSignup(page, testEmail, { fullName: 'E2E Test User' })
    await page.click('button[type="submit"]')

    // Registration asks the user to verify their email first
    await expect(page.getByText('Check your email')).toBeVisible({ timeout: 15000 })

    // Following the link verifies the account and signs the user in
    await verifyFromEmail(page, testEmail)
    await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 15000 })
  })

  test('should register without full name (optional field)', async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')

    await fillSignup(page, generateTestEmail())
    await page.click('button[type="submit"]')

    await expect(page.getByText('Check your email')).toBeVisible({ timeout: 15000 })
  })

  test('should show error for weak password', async ({ page }) => {
    await fillSignup(page, generateTestEmail(), { password: 'short' })
    await page.click('button[type="submit"]')

    await expect(page.locator('[role="alert"]')).toHaveText('Password must meet all requirements', {
      timeout: 5000,
    })
    await expect(page).toHaveURL(/\/signup/)
  })

  test('should show error for password mismatch', async ({ page }) => {
    await fillSignup(page, generateTestEmail(), {
      password: 'ValidPassword123!',
      confirmPassword: 'DifferentPassword123!',
    })
    await page.click('button[type="submit"]')

    await expect(page.locator('[role="alert"]')).toHaveText('Passwords do not match', {
      timeout: 5000,
    })
    await expect(page).toHaveURL(/\/signup/)
  })

  test('should not submit with empty required fields', async ({ page }) => {
    // Try to submit empty form
    await page.click('button[type="submit"]')

    // Form should not submit (HTML5 validation)
    await expect(page).toHaveURL(/\/signup/)
    await expect(page.locator('#businessName')).toHaveAttribute('required', '')
    await expect(page.locator('#email')).toHaveAttribute('required', '')
  })

  test('should show loading state during registration', async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')

    await fillSignup(page, generateTestEmail())

    // Hold the request so the loading state is observable
    await page.route('**/onboarding/register', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      await route.continue()
    })

    const submitButton = page.locator('button[type="submit"]')
    await submitButton.click()
    await expect(submitButton).toBeDisabled()
    await expect(submitButton).toHaveText(/Creating account/)

    await expect(page.getByText('Check your email')).toBeVisible({ timeout: 15000 })
  })

  test('should navigate to login page', async ({ page }) => {
    await page.click('text=Sign in')
    await expect(page).toHaveURL(/\/login/)
  })

  test('should have accessible form labels', async ({ page }) => {
    await expect(page.getByLabel('Business Name')).toBeVisible()
    await expect(page.getByLabel('Full Name')).toBeVisible()
    await expect(page.getByLabel('Email')).toBeVisible()
    await expect(page.getByLabel('Password *', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Confirm Password')).toBeVisible()
  })
})

test.describe('Registration - Duplicate Email', () => {
  let existingEmail = ''

  test.beforeAll(async ({ browser }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    // A verified account owns the email
    const page = await browser.newPage()
    existingEmail = await registerAndLogin(page)
    await page.close()
  })

  test('should show error when registering with existing email', async ({ page }) => {
    await page.goto('/signup')
    await fillSignup(page, existingEmail)
    await page.click('button[type="submit"]')

    await expect(page.locator('[role="alert"]')).toBeVisible({ timeout: 10000 })
    await expect(page).toHaveURL(/\/signup/)
  })
})

test.describe('Registration - Dashboard Onboarding', () => {
  test.beforeEach(async () => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
  })

  test('new user lands on the dashboard after verifying', async ({ page }) => {
    await registerAndLogin(page)
    await expect(page).toHaveURL(/\/dashboard/)
    await page.waitForLoadState('networkidle')
  })

  test('new user can navigate to key areas after registration', async ({ page }) => {
    await registerAndLogin(page)

    // /inventory is the old address of the filament page
    await page.goto('/filaments')
    await expect(page).toHaveURL(/\/filaments/)

    await page.goto('/products')
    await expect(page).toHaveURL(/\/products/)
  })
})
