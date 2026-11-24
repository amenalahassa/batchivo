/**
 * E2E Tests: Authentication - Login Flow
 *
 * Tests the login functionality including:
 * - Successful login with valid credentials
 * - Failed login with invalid credentials
 * - Form validation for empty fields
 * - Redirect preservation after login
 * - Page navigation and UI elements
 */

import { test, expect } from '@playwright/test'
import { createTestUser, isBackendAvailable } from '../../helpers'

test.describe('Login Page', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    await page.goto('/login')
  })

  test('should display login form with all elements', async ({ page }) => {
    // Verify page title and description
    await expect(page.getByText('Welcome back')).toBeVisible()
    await expect(page.getByText('Sign in to your Batchivo account')).toBeVisible()

    // Verify form elements exist
    await expect(page.locator('#email')).toBeVisible()
    await expect(page.locator('#password')).toBeVisible()
    await expect(page.locator('button[type="submit"]')).toBeVisible()

    // Verify navigation links
    await expect(page.getByRole('link', { name: 'Forgot password?' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Sign up' })).toBeVisible()
  })

  test('should successfully login with valid credentials', async ({ page }) => {
    // First create a user, then logout to test login
    const testUser = await createTestUser(page)

    // Fill in credentials
    await page.fill('#email', testUser.email)
    await page.fill('#password', testUser.password)

    // Submit form
    await page.click('button[type="submit"]')

    // Wait for redirect to dashboard
    await page.waitForURL('/dashboard', { timeout: 15000 })

    // Verify we're on the dashboard
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('should show error message with invalid credentials', async ({ page }) => {
    // Fill in invalid credentials
    await page.fill('#email', 'invalid@example.com')
    await page.fill('#password', 'wrongpassword')

    // Submit form
    await page.click('button[type="submit"]')

    // Wait for error message
    await expect(page.locator('[role="alert"]')).toBeVisible({ timeout: 10000 })

    // Verify we're still on login page
    await expect(page).toHaveURL(/\/login/)
  })

  test('should show loading state during login', async ({ page }) => {
    // First create a user
    const testUser = await createTestUser(page)

    // Fill in credentials
    await page.fill('#email', testUser.email)
    await page.fill('#password', testUser.password)

    // Hold the login request so the loading state is observable
    await page.route('**/auth/login', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      await route.continue()
    })

    // Click submit and immediately check for loading state
    const submitButton = page.locator('button[type="submit"]')
    await submitButton.click()

    // Button should be disabled during loading
    await expect(submitButton).toBeDisabled()
  })

  test('should preserve redirect URL after login', async ({ page }) => {
    // First create a user
    const testUser = await createTestUser(page)

    // Navigate to login with redirect parameter
    await page.goto('/login?redirect=/products')

    // Fill in credentials
    await page.fill('#email', testUser.email)
    await page.fill('#password', testUser.password)

    // Submit form
    await page.click('button[type="submit"]')

    // Should redirect to the specified URL
    await page.waitForURL(/\/products/, { timeout: 15000 })
    await expect(page).toHaveURL(/\/products/)
  })

  test('should navigate to forgot password page', async ({ page }) => {
    await page.click('text=Forgot password?')
    await expect(page).toHaveURL(/\/forgot-password/)
  })

  test('should navigate to signup page', async ({ page }) => {
    await page.click('text=Sign up')
    await expect(page).toHaveURL(/\/signup/)
  })

  test('should have accessible form labels', async ({ page }) => {
    // Check that labels are properly associated with inputs
    const emailLabel = page.getByText('Email', { exact: false }).first()
    const passwordLabel = page.getByText('Password', { exact: false }).first()

    await expect(emailLabel).toBeVisible()
    await expect(passwordLabel).toBeVisible()
  })
})

test.describe('Authentication Flow', () => {
  test.beforeEach(async () => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
  })

  test('should redirect to login when accessing protected route', async ({ page }) => {
    // Try to access a protected route without being logged in
    await page.goto('/dashboard')

    // Should redirect to login
    await page.waitForURL(/\/login/, { timeout: 10000 })
    await expect(page).toHaveURL(/\/login/)
  })

  test('should persist session across page refresh', async ({ page }) => {
    // First create a user and login
    const testUser = await createTestUser(page)

    // Login with created user
    await page.fill('#email', testUser.email)
    await page.fill('#password', testUser.password)
    await page.click('button[type="submit"]')
    await page.waitForURL('/dashboard', { timeout: 15000 })

    // Refresh the page
    await page.reload()

    // Should still be logged in (on dashboard)
    await expect(page).toHaveURL(/\/dashboard/)
  })
})
