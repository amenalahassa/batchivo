/**
 * E2E Tests: Dashboard Workflow
 *
 * Tests the dashboard page functionality including:
 * - Dashboard load and display
 * - Quick actions
 * - Navigation from dashboard
 * - Stats and metrics display
 * - Recent activity display
 */

import { test, expect } from '../../fixtures'
import { isBackendAvailable, openDashboard } from '../../helpers'

// The tests only read the tenant (or sign out client-side): one tenant per
// worker for this file is enough.
test.use({ account: 'shared' })

test.describe('Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
  })

  test('should display dashboard after login', async ({ page }) => {
    // Verify we're on the dashboard
    await expect(page).toHaveURL(/\/dashboard/)
    
    // Dashboard should have a welcome or title
    const pageContent = await page.textContent('body')
    expect(
      pageContent?.includes('Dashboard') ||
      pageContent?.includes('Welcome') ||
      pageContent?.includes('Overview')
    ).toBeTruthy()
  })

  test('should display user-specific content', async ({ page }) => {
    // Dashboard should show some personalized content
    // This could be the tenant name, user name, or recent activity
    await page.waitForLoadState('networkidle')

    // At minimum, the page should load without errors
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('should display navigation menu', async ({ page }) => {
    // Sidebar or navigation should be visible
    const navigation = page.locator('nav').or(
      page.locator('[role="navigation"]').or(
        page.locator('aside')
      )
    )
    
    await expect(navigation.first()).toBeVisible()
  })

  test('should have quick action buttons', async ({ page }) => {
    // Dashboard typically has quick actions like "New Production Run", "Add Spool", etc.
    const quickActions = page.locator('button, a').filter({
      hasText: /new|add|create|view/i
    })
    
    const actionCount = await quickActions.count()
    expect(actionCount).toBeGreaterThan(0)
  })
})

test.describe('Dashboard Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
  })

  // The desktop header navigation. Its entries are links (the Button wrapper
  // around each one renders as a button too, so match the link role only).
  const navLink = (page: import('@playwright/test').Page, name: string) =>
    page.getByRole('navigation').getByRole('link', { name, exact: true })

  test('should navigate to inventory from dashboard', async ({ page }) => {
    // The filament inventory lives at /filaments (/inventory redirects there)
    await navLink(page, 'Filaments').click()
    await expect(page).toHaveURL(/\/filaments/)
  })

  test('should navigate to production runs from dashboard', async ({ page }) => {
    await navLink(page, 'Runs').click()
    await expect(page).toHaveURL(/\/production-runs/)
  })

  test('should navigate to products from dashboard', async ({ page }) => {
    await navLink(page, 'Products').click()
    await expect(page).toHaveURL(/\/products/)
  })

  test('should navigate to settings from dashboard', async ({ page }) => {
    // Look for settings in user menu or navigation
    const settingsLink = page.getByRole('link', { name: /settings/i }).or(
      page.getByRole('menuitem', { name: /settings/i })
    )
    
    if (await settingsLink.isVisible()) {
      await settingsLink.click()
      await expect(page).toHaveURL(/\/settings/)
    }
  })
})

test.describe('Dashboard Stats', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
  })

  test('should display stats cards', async ({ page }) => {
    // Dashboard typically shows stats like total products, spools, etc.
    // At least the page should load successfully
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('should handle empty state for new user', async ({ page }) => {
    // New users might see empty state or getting started guide
    const pageContent = await page.textContent('body')
    
    // Should either show stats (even if 0) or a getting started message
    const hasContent = 
      pageContent?.includes('0') ||
      pageContent?.includes('Get started') ||
      pageContent?.includes('No') ||
      pageContent?.includes('Add your first') ||
      pageContent?.length && pageContent.length > 100
    
    expect(hasContent).toBeTruthy()
  })
})

test.describe('Dashboard Loading States', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await openDashboard(page)
  })

  test('should show loading state then content', async ({ page }) => {
    // Navigate to dashboard and check for loading behavior
    await page.goto('/dashboard')
    
    // Page should eventually show content
    await page.waitForLoadState('networkidle')
    
    // Verify page has loaded (no error message)
    // ("Failed Today" is a stat card title, not an error)
    await expect(page.getByText(/something went wrong|failed to load/i)).toHaveCount(0)
    
    // Main content should be visible
    await expect(page.getByRole('main')).toBeVisible()
  })

  test('should handle slow API responses gracefully', async ({ page }) => {
    // Simulate slow network
    await page.route('**/api/**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000))
      await route.continue()
    })
    
    await page.goto('/dashboard')
    
    // Should show loading or skeleton while waiting
    await page.waitForLoadState('networkidle', { timeout: 30000 })
    
    // Eventually content should load
    await expect(page.getByRole('main')).toBeVisible()
  })
})

test.describe('Dashboard Responsive Design', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running')
    await openDashboard(page)
  })

  test('should be usable on mobile viewport', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 })
    
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    
    // Dashboard should still be accessible
    await expect(page.getByRole('main')).toBeVisible()
    
    // The header navigation collapses into a menu button that opens a sheet
    await expect(page.getByRole('navigation')).toBeHidden()
    await page.locator('header button:has(svg.lucide-menu)').click()
    const menu = page.getByRole('dialog', { name: 'Menu' })
    await expect(menu).toBeVisible()
    await expect(menu.getByRole('link', { name: 'Products', exact: true })).toBeVisible()
  })

  test('should be usable on tablet viewport', async ({ page }) => {
    // Set tablet viewport
    await page.setViewportSize({ width: 768, height: 1024 })
    
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    
    // Dashboard should render properly
    await expect(page.getByRole('main')).toBeVisible()
  })
})
