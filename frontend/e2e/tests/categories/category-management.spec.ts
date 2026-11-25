/**
 * E2E Tests: Category Management
 *
 * Tests the category management functionality:
 * - Create new category
 * - Edit existing category
 * - Toggle active status
 * - Reorder categories
 * - Delete category
 * - Search categories
 *
 * Every test signs up a fresh tenant, so nothing needs cleaning up afterwards.
 * Desktop viewport: the categories show as table rows (the mobile cards are
 * hidden), so rows are found by role.
 */

import { test, expect, type Page } from '@playwright/test'
import { apiAs, isBackendAvailable, registerAndLogin, uniqueSuffix } from '../../helpers'

// Generate unique test data
const generateTestCategory = () => {
  const suffix = uniqueSuffix()
  return {
    name: `E2E Test Category ${suffix}`,
    slug: `e2e-test-category-${suffix}`,
    description: 'Category created by automated E2E test',
  }
}

type TestCategory = ReturnType<typeof generateTestCategory>

// Helper: Navigate to categories page
async function navigateToCategories(page: Page) {
  await page.goto('/categories')
  await expect(page.getByRole('heading', { level: 2, name: 'Categories' })).toBeVisible()
}

/** The table row of a category. */
function categoryRow(page: Page, name: string) {
  return page.getByRole('row').filter({ hasText: name })
}

// Helper: Create a category via the dialog
async function createCategory(page: Page, category: TestCategory): Promise<void> {
  await navigateToCategories(page)

  await page.getByRole('button', { name: 'New Category' }).click()
  const dialog = page.getByRole('dialog', { name: 'Create Category' })
  await expect(dialog).toBeVisible()

  await dialog.getByLabel('Name').fill(category.name)
  await dialog.getByLabel('Slug').fill(category.slug)
  await dialog.getByLabel('Description').fill(category.description)

  await dialog.getByRole('button', { name: 'Create Category' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(categoryRow(page, category.name)).toBeVisible()
}

async function search(page: Page, text: string) {
  await page.getByPlaceholder('Search by name...').fill(text)
}

test.describe('Category Management', () => {
  let testCategory: TestCategory

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    testCategory = generateTestCategory()
    await registerAndLogin(page)
  })

  test('should display categories page', async ({ page }) => {
    await navigateToCategories(page)

    await expect(page.getByRole('button', { name: 'New Category' })).toBeVisible()
    await expect(page.getByPlaceholder('Search by name...')).toBeVisible()
    await expect(
      page.getByText('No categories yet. Create your first category to organize products.')
    ).toBeVisible()
  })

  test('should create a new category', async ({ page }) => {
    await createCategory(page, testCategory)

    // Persisted: still there after a reload
    await navigateToCategories(page)
    const row = categoryRow(page, testCategory.name)
    await expect(row).toBeVisible()
    await expect(row).toContainText(testCategory.slug)
    await expect(row).toContainText(testCategory.description)
  })

  test('should auto-generate slug from name', async ({ page }) => {
    await navigateToCategories(page)

    await page.getByRole('button', { name: 'New Category' }).click()
    const dialog = page.getByRole('dialog', { name: 'Create Category' })
    await expect(dialog).toBeVisible()

    await dialog.getByLabel('Name').fill('My Test Category')
    await expect(dialog.getByLabel('Slug')).toHaveValue('my-test-category')

    // Close dialog without saving
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
  })

  test('should edit an existing category', async ({ page }) => {
    await createCategory(page, testCategory)

    const row = categoryRow(page, testCategory.name)
    await row.hover()
    await row.getByRole('button').filter({ has: page.locator('svg.lucide-pencil') }).click()

    const dialog = page.getByRole('dialog', { name: 'Edit Category' })
    await expect(dialog).toBeVisible()

    const updatedName = `${testCategory.name} - Updated`
    await dialog.getByLabel('Name').fill(updatedName)
    await dialog.getByRole('button', { name: 'Save Changes' }).click()
    await expect(dialog).not.toBeVisible()

    await expect(categoryRow(page, updatedName)).toBeVisible()
  })

  test('should toggle category active status', async ({ page }) => {
    await createCategory(page, testCategory)

    const toggle = categoryRow(page, testCategory.name).getByRole('switch')
    await expect(toggle).toHaveAttribute('data-state', 'checked')
    await toggle.click()

    // Switched off: the active-only list drops it, and the API says inactive
    await expect(categoryRow(page, testCategory.name)).toHaveCount(0)
    const api = await apiAs(page)
    const list = await api.get('/api/v1/categories?include_inactive=true')
    const saved = list.categories.find((c: { name: string }) => c.name === testCategory.name)
    expect(saved.is_active).toBe(false)
  })

  test('should list inactive categories under Show All', async ({ page }) => {
    // Regression: .specify/bugs/category-show-all-param
    await createCategory(page, testCategory)
    await categoryRow(page, testCategory.name).getByRole('switch').click()
    await page.getByRole('button', { name: /^Show All/ }).click()
    await expect(categoryRow(page, testCategory.name).getByRole('switch')).toHaveAttribute(
      'data-state',
      'unchecked'
    )
  })

  test('should search categories', async ({ page }) => {
    await createCategory(page, testCategory)

    await search(page, testCategory.name)
    await expect(categoryRow(page, testCategory.name)).toBeVisible()

    await search(page, 'nonexistent-category-xyz-12345')
    await expect(page.getByText('No categories match your search')).toBeVisible()
    await expect(categoryRow(page, testCategory.name)).toHaveCount(0)
  })

  test('should filter active/inactive categories', async ({ page }) => {
    await navigateToCategories(page)

    const activeOnly = page.getByRole('button', { name: /^Active \(/ })
    const showAll = page.getByRole('button', { name: /^Show All/ })
    await expect(activeOnly).toBeVisible()
    await expect(showAll).toBeVisible()

    await showAll.click()
    await activeOnly.click()
  })

  test('should delete a category', async ({ page }) => {
    await createCategory(page, testCategory)

    const row = categoryRow(page, testCategory.name)
    await row.hover()
    await row.getByRole('button').filter({ has: page.locator('svg.lucide-trash-2') }).click()

    const confirm = page.getByRole('alertdialog')
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Delete' }).click()
    await expect(confirm).not.toBeVisible()

    await expect(categoryRow(page, testCategory.name)).toHaveCount(0)
  })
})

test.describe('Category Reordering', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    await registerAndLogin(page)
  })

  const up = (page: Page, name: string) =>
    categoryRow(page, name).getByRole('button').filter({ has: page.locator('svg.lucide-arrow-up') })
  const down = (page: Page, name: string) =>
    categoryRow(page, name).getByRole('button').filter({ has: page.locator('svg.lucide-arrow-down') })

  test('should have reorder buttons', async ({ page }) => {
    // Two categories with distinct display orders
    const first = generateTestCategory()
    const second = generateTestCategory()
    const api = await apiAs(page)
    await api.post('/api/v1/categories', { name: first.name, display_order: 1 })
    await api.post('/api/v1/categories', { name: second.name, display_order: 2 })

    await navigateToCategories(page)
    const rows = page.getByRole('row').filter({ hasText: 'E2E Test Category' })
    await expect(rows).toHaveCount(2)
    await expect(rows.nth(0)).toContainText(first.name)

    // The first row cannot move up, the last cannot move down
    await expect(up(page, first.name)).toBeDisabled()
    await expect(down(page, second.name)).toBeDisabled()

    // Moving the first one down swaps them
    await down(page, first.name).click()
    await expect(rows.nth(0)).toContainText(second.name)
    await expect(rows.nth(1)).toContainText(first.name)
  })

  test('should reorder categories created from the dialog', async ({ page }) => {
    // Regression: .specify/bugs/category-reorder-noop
    const first = generateTestCategory()
    const second = generateTestCategory()
    await createCategory(page, first)
    await createCategory(page, second)

    const rows = page.getByRole('row').filter({ hasText: 'E2E Test Category' })
    const firstName = (await rows.nth(0).getByRole('cell').nth(1).textContent())!.trim()
    const secondName = (await rows.nth(1).getByRole('cell').nth(1).textContent())!.trim()
    await down(page, firstName).click()
    await expect(rows.nth(0)).toContainText(secondName)
  })
})
