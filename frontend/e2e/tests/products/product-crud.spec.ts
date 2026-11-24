/**
 * E2E Tests: Product CRUD Operations
 *
 * Tests the complete product lifecycle:
 * - Create product with required fields
 * - View product details
 * - Update product information
 * - Deactivate product
 * - SKU auto-generation
 *
 * Each test runs in a fresh tenant, so it creates the products it needs.
 */

import { test, expect, type Page } from '@playwright/test'
import { apiAs, isBackendAvailable, registerAndLogin } from '../../helpers'

const PRODUCT_DETAIL_URL = /\/products\/[0-9a-f-]{36}$/
const PRODUCT_EDIT_URL = /\/products\/[0-9a-f-]{36}\/edit$/

// Generate unique test data using timestamp
const generateTestProduct = () => ({
  sku: `TEST-PROD-${Date.now()}`,
  name: `E2E Test Product ${Date.now()}`,
  description: 'Product created by automated E2E test',
  packaging_cost: '1.50',
  assembly_minutes: '10',
  units_in_stock: '5',
})

// Helper: Navigate to products page and wait for the list to settle
async function navigateToProducts(page: Page) {
  await page.goto('/products')
  await expect(page.getByRole('heading', { level: 2, name: 'Products', exact: true })).toBeVisible()
  await expect(page.getByText('Loading products...')).toHaveCount(0)
}

// Helper: Open the quick-create form from the products list
async function openQuickCreate(page: Page) {
  await navigateToProducts(page)
  await page.getByRole('link', { name: 'Quick Create' }).click()
  await page.waitForURL('/products/new', { timeout: 10000 })
  // The form fills in the next free SKU once it arrives.
  await expect(page.locator('input[name="sku"]')).toHaveValue(/^PROD-/, { timeout: 10000 })
}

// Helper: Create a product through the quick-create form; lands on its detail page
async function createProductViaForm(page: Page, sku: string, name: string) {
  await openQuickCreate(page)
  await page.fill('input[name="sku"]', sku)
  await page.fill('input[name="name"]', name)
  await page.getByRole('button', { name: 'Create Product' }).click()
  await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 15000 })
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
}

test.describe('Product CRUD Operations', () => {
  let testProduct: ReturnType<typeof generateTestProduct>

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    testProduct = generateTestProduct()
    await registerAndLogin(page)
  })

  test('should display products list page', async ({ page }) => {
    await navigateToProducts(page)

    // Verify page elements
    await expect(page.getByRole('button', { name: 'Create with Wizard' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Quick Create' })).toBeVisible()
    await expect(page.getByPlaceholder('Search by SKU or name...')).toBeVisible()
  })

  test('should create a new product with basic fields', async ({ page }) => {
    await openQuickCreate(page)

    // Fill in product form
    await page.fill('input[name="sku"]', testProduct.sku)
    await page.fill('input[name="name"]', testProduct.name)
    await page.locator('.ProseMirror').fill(testProduct.description)
    await page.fill('input[name="packaging_cost"]', testProduct.packaging_cost)
    await page.fill('input[name="assembly_minutes"]', testProduct.assembly_minutes)
    await page.fill('input[name="units_in_stock"]', testProduct.units_in_stock)

    // Submit form
    await page.getByRole('button', { name: 'Create Product' }).click()

    // Wait for redirect to product detail page
    await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 15000 })

    // Verify product was created with its fields
    await expect(page.getByRole('heading', { level: 1, name: testProduct.name })).toBeVisible()
    await expect(page.getByText(testProduct.description)).toBeVisible()
    await expect(page.getByText(`${testProduct.assembly_minutes} minutes`)).toBeVisible()
  })

  test('should auto-generate SKU for new product', async ({ page }) => {
    await openQuickCreate(page)

    // First product of a fresh tenant: PROD-001
    await expect(page.locator('input[name="sku"]')).toHaveValue(/^PROD-\d{3,}$/)
  })

  test('should view product details', async ({ page }) => {
    await createProductViaForm(page, testProduct.sku, testProduct.name)

    // Verify detail page shows product information
    await expect(page.getByText(testProduct.sku).first()).toBeVisible()
    await expect(page.getByRole('heading', { level: 1, name: testProduct.name })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Edit' })).toBeVisible()
  })

  test('should edit an existing product', async ({ page }) => {
    await createProductViaForm(page, testProduct.sku, testProduct.name)

    // Navigate to edit page
    await page.getByRole('link', { name: 'Edit' }).click()
    await page.waitForURL(PRODUCT_EDIT_URL, { timeout: 10000 })

    // Update product name
    const updatedName = `${testProduct.name} - Updated`
    await expect(page.locator('input[name="name"]')).toHaveValue(testProduct.name)
    await page.fill('input[name="name"]', updatedName)

    // Save changes
    await page.getByRole('button', { name: 'Save Changes' }).click()
    await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 15000 })

    // Verify update
    await expect(page.getByRole('heading', { level: 1, name: updatedName })).toBeVisible()
  })

  test('should search for products', async ({ page }) => {
    // Two products, only one matching the search
    const api = await apiAs(page)
    await api.post('/api/v1/products', { sku: testProduct.sku, name: testProduct.name })
    const otherName = `Other Product ${Date.now()}`
    await api.post('/api/v1/products', { sku: `OTHER-${Date.now()}`, name: otherName })

    await navigateToProducts(page)
    const rows = page.getByRole('row')
    await expect(rows.filter({ hasText: otherName })).toBeVisible()

    // Search for the product
    await page.getByPlaceholder('Search by SKU or name...').fill(testProduct.name)

    // Verify only the matching product remains
    await expect(rows.filter({ hasText: testProduct.name })).toBeVisible()
    await expect(rows.filter({ hasText: otherName })).toHaveCount(0)
  })

  // App bug: GET /api/v1/products/{id} only finds active products
  // (backend/app/api/v1/products.py:650, `Product.is_active.is_(True)`), so after
  // saving a product as inactive the form's redirect lands on "Error loading
  // product" (404) instead of the detail page with its "Inactive" badge.
  test.fixme('should toggle product active status', async ({ page }) => {
    await createProductViaForm(page, testProduct.sku, testProduct.name)
    await expect(page.getByText('Active', { exact: true })).toBeVisible()

    // Navigate to edit page
    await page.getByRole('link', { name: 'Edit' }).click()
    await page.waitForURL(PRODUCT_EDIT_URL, { timeout: 10000 })

    // Toggle active status off
    const activeSwitch = page.getByRole('switch', { name: 'Active Status' })
    await expect(activeSwitch).toHaveAttribute('data-state', 'checked')
    await activeSwitch.click()
    await expect(activeSwitch).toHaveAttribute('data-state', 'unchecked')

    await page.getByRole('button', { name: 'Save Changes' }).click()
    await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 15000 })

    await expect(page.getByText('Inactive', { exact: true })).toBeVisible()
  })

  test('should validate required fields', async ({ page }) => {
    await openQuickCreate(page)

    // Clear the auto-generated SKU
    await page.fill('input[name="sku"]', '')

    // Try to submit without filling required fields
    await page.getByRole('button', { name: 'Create Product' }).click()

    // Should see validation messages and stay on the create page
    await expect(page.getByText('SKU is required')).toBeVisible()
    await expect(page.getByText('Name is required')).toBeVisible()
    await expect(page).toHaveURL('/products/new')
  })
})

test.describe('Product List Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    await registerAndLogin(page)
  })

  test('should navigate to product detail on row click', async ({ page }) => {
    const name = `Row Click Product ${Date.now()}`
    await (await apiAs(page)).post('/api/v1/products', { sku: `ROW-${Date.now()}`, name })
    await navigateToProducts(page)

    const row = page.getByRole('row').filter({ hasText: name })
    await row.getByRole('link', { name }).click()
    await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 10000 })
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
  })

  test('should filter active/inactive products', async ({ page }) => {
    const api = await apiAs(page)
    const activeName = `Live Product ${Date.now()}`
    const inactiveName = `Retired Product ${Date.now()}`
    await api.post('/api/v1/products', { sku: `ACT-${Date.now()}`, name: activeName })
    await api.post('/api/v1/products', {
      sku: `INACT-${Date.now()}`,
      name: inactiveName,
      is_active: false,
    })

    await navigateToProducts(page)
    const rows = page.getByRole('row')
    await expect(rows.filter({ hasText: activeName })).toBeVisible()
    await expect(rows.filter({ hasText: inactiveName })).toBeVisible()

    // Active filter: only the active product
    const activeButton = page.getByRole('button', { name: /^Active \(\d+\)$/ })
    await activeButton.click()
    await expect(rows.filter({ hasText: activeName })).toBeVisible()
    await expect(rows.filter({ hasText: inactiveName })).toHaveCount(0)

    // Click again to clear filter
    await activeButton.click()
    await expect(rows.filter({ hasText: inactiveName })).toBeVisible()

    // Inactive filter: only the inactive product
    await page.getByRole('button', { name: /^Inactive \(\d+\)$/ }).click()
    await expect(rows.filter({ hasText: inactiveName })).toBeVisible()
    await expect(rows.filter({ hasText: activeName })).toHaveCount(0)
  })

  test('should sort products', async ({ page }) => {
    const api = await apiAs(page)
    const stamp = Date.now()
    // Most recent first lists Zulu before Alpha; Name (A-Z) reverses that.
    await api.post('/api/v1/products', { sku: `SORT-A-${stamp}`, name: `Alpha ${stamp}` })
    await api.post('/api/v1/products', { sku: `SORT-Z-${stamp}`, name: `Zulu ${stamp}` })

    await navigateToProducts(page)
    const productLinks = page.locator('tbody tr').getByRole('link').filter({ hasText: String(stamp) })
    await expect(productLinks).toHaveText([`Zulu ${stamp}`, `Alpha ${stamp}`])

    // Open sort dropdown and select Name sort
    await page.getByRole('combobox').filter({ hasText: 'Most Recent' }).click()
    await page.getByRole('option', { name: 'Name (A-Z)' }).click()

    await expect(productLinks).toHaveText([`Alpha ${stamp}`, `Zulu ${stamp}`])
  })
})
