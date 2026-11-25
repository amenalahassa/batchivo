/**
 * E2E Tests: Products - Field Validation
 *
 * Comprehensive tests verifying that each product form field correctly
 * saves to the database and is displayed properly in the UI.
 *
 * Product Fields Tested:
 * - Required: sku, name
 * - Optional text: description, shop_description, feature_title, backstory
 * - Numeric: packaging_cost, assembly_minutes, units_in_stock
 * - Boolean: shop_visible, is_featured
 */

import { type Page } from '@playwright/test'
import { test, expect } from '../../fixtures'
import { apiAs, isBackendAvailable, openDashboard } from '../../helpers'

const PRODUCT_DETAIL_URL = /\/products\/[0-9a-f-]{36}$/
const PRODUCT_EDIT_URL = /\/products\/[0-9a-f-]{36}\/edit$/

function generateCompleteProductData() {
  const timestamp = Date.now()
  return {
    sku: `PROD-TEST-${timestamp}`,
    name: `Test Product ${timestamp}`,
    description: 'A comprehensive test product with all fields populated',
    packaging_cost: 1.50,
    packaging_quantity: 2,
    assembly_minutes: 15,
    units_in_stock: 10,
    shop_description: 'Customer-facing description for the shop',
    feature_title: 'Featured Test Dragon',
    backstory: 'An ancient dragon awakened from slumber...',
  }
}

// Wait for the create form, including its auto-generated SKU: submitting
// before the SKU arrives fails validation ("SKU is required").
async function waitForProductForm(page: Page): Promise<void> {
  await expect(page.locator('input[name="name"]')).toBeVisible({ timeout: 10000 })
  await expect(page.locator('input[name="sku"]')).toHaveValue(/^PROD-/, { timeout: 10000 })
}

// Helper to fill required product fields
async function fillRequiredProductFields(page: Page, name: string, sku?: string): Promise<void> {
  if (sku) {
    await page.locator('input[name="sku"]').fill(sku)
  }
  await page.locator('input[name="name"]').fill(name)
}

// The description is a rich-text (TipTap) editor, not a textarea.
function descriptionEditor(page: Page) {
  return page.locator('.ProseMirror')
}

// Submit the create form, land on the new product's page, and return its id.
async function submitProduct(page: Page): Promise<string> {
  await page.getByRole('button', { name: /create product/i }).click()
  await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 30000 })
  return page.url().split('/').pop()!
}

// Helper to submit form and verify redirect
async function submitAndVerifyProduct(page: Page, verifyText: string): Promise<string> {
  const productId = await submitProduct(page)
  await expect(page.getByText(verifyText).first()).toBeVisible({ timeout: 10000 })
  return productId
}

async function fetchProduct(page: Page, productId: string) {
  return (await apiAs(page)).get(`/api/v1/products/${productId}`)
}

// Create a product through the form, then open its edit page.
async function createAndOpenEdit(page: Page, name: string): Promise<string> {
  await page.goto('/products/new')
  await waitForProductForm(page)
  await page.locator('input[name="name"]').fill(name)
  const productId = await submitProduct(page)

  await page.getByRole('link', { name: 'Edit' }).click()
  await page.waitForURL(PRODUCT_EDIT_URL, { timeout: 30000 })
  await expect(page.locator('input[name="name"]')).toHaveValue(name)
  return productId
}

async function saveChanges(page: Page): Promise<void> {
  await page.getByRole('button', { name: /save changes/i }).click()
  await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 30000 })
}

test.describe('Product Field Validation - Required Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/products/new')
  })

  test('should display product creation form with all elements', async ({ page }) => {
    await waitForProductForm(page)
    await expect(page.getByText('Basic Information')).toBeVisible()
    await expect(page.locator('input[name="sku"]')).toBeVisible()
    await expect(page.locator('input[name="name"]')).toBeVisible()
  })

  test('should save sku correctly', async ({ page }) => {
    const testData = generateCompleteProductData()

    await waitForProductForm(page)
    await fillRequiredProductFields(page, testData.name, testData.sku)
    await submitAndVerifyProduct(page, testData.sku)
  })

  test('should save name correctly', async ({ page }) => {
    const uniqueName = `Unique Product Name ${Date.now()}`

    await waitForProductForm(page)
    await fillRequiredProductFields(page, uniqueName)
    await submitAndVerifyProduct(page, uniqueName)
  })

  test('should require name field', async ({ page }) => {
    await waitForProductForm(page)
    // Only fill SKU, leave name empty
    await page.locator('input[name="sku"]').fill('TEST-SKU-123')

    await page.getByRole('button', { name: /create product/i }).click()

    // Should show validation error and stay on form
    await expect(page.getByText('Name is required')).toBeVisible()
    await expect(page).toHaveURL(/\/products\/new/)
  })
})

test.describe('Product Field Validation - Optional Text Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/products/new')
  })

  test('should save description correctly', async ({ page }) => {
    const uniqueName = `Product Desc Test ${Date.now()}`
    const description = 'This is a detailed product description with special chars: !@#$%'

    await waitForProductForm(page)
    await fillRequiredProductFields(page, uniqueName)
    await descriptionEditor(page).fill(description)

    await submitProduct(page)

    // Description should appear on detail page
    await expect(page.getByText(description)).toBeVisible()
  })
})

test.describe('Product Field Validation - Numeric Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await page.goto('/products/new')
  })

  test('should save packaging_cost correctly', async ({ page }) => {
    const testData = generateCompleteProductData()

    await waitForProductForm(page)
    await fillRequiredProductFields(page, testData.name)
    await page.locator('input[name="packaging_cost"]').fill('2.50')

    const productId = await submitAndVerifyProduct(page, testData.name)
    expect(Number((await fetchProduct(page, productId)).packaging_cost)).toBe(2.5)
  })

  test('should save assembly_minutes correctly', async ({ page }) => {
    const testData = generateCompleteProductData()

    await waitForProductForm(page)
    await fillRequiredProductFields(page, testData.name)
    await page.locator('input[name="assembly_minutes"]').fill('30')

    await submitAndVerifyProduct(page, testData.name)
    await expect(page.getByText('30 minutes')).toBeVisible()
  })

  test('should save units_in_stock correctly', async ({ page }) => {
    const testData = generateCompleteProductData()

    await waitForProductForm(page)
    await fillRequiredProductFields(page, testData.name)
    await page.locator('input[name="units_in_stock"]').fill('25')

    const productId = await submitProduct(page)

    // Stock count should appear on detail page
    const stockRow = page.getByText('Units in Stock', { exact: true }).locator('..')
    await expect(stockRow).toContainText('25')
    expect((await fetchProduct(page, productId)).units_in_stock).toBe(25)
  })
})

test.describe('Product Field Validation - Complete Form', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await openDashboard(page)
  })

  test('should create product with all fields populated', async ({ page }) => {
    const testData = generateCompleteProductData()

    await page.goto('/products/new')
    await waitForProductForm(page)

    // Required fields
    await page.locator('input[name="sku"]').fill(testData.sku)
    await page.locator('input[name="name"]').fill(testData.name)

    // Optional text fields
    await descriptionEditor(page).fill(testData.description)

    // Numeric fields
    await page.locator('input[name="packaging_cost"]').fill(testData.packaging_cost.toString())
    await page.locator('input[name="assembly_minutes"]').fill(testData.assembly_minutes.toString())
    await page.locator('input[name="units_in_stock"]').fill(testData.units_in_stock.toString())

    const productId = await submitAndVerifyProduct(page, testData.name)

    const saved = await fetchProduct(page, productId)
    expect(saved.sku).toBe(testData.sku)
    expect(saved.description).toContain(testData.description)
    expect(Number(saved.packaging_cost)).toBe(testData.packaging_cost)
    expect(saved.assembly_minutes).toBe(testData.assembly_minutes)
    expect(saved.units_in_stock).toBe(testData.units_in_stock)
  })

  test('should verify created product data via API', async ({ page }) => {
    const testData = generateCompleteProductData()
    const uniqueSku = `API-PROD-${Date.now()}`

    await page.goto('/products/new')
    await waitForProductForm(page)

    await page.locator('input[name="sku"]').fill(uniqueSku)
    await page.locator('input[name="name"]').fill(testData.name)
    await descriptionEditor(page).fill('API test description')

    const productId = await submitProduct(page)

    // Verify via API (the editor stores the description as HTML)
    const data = await fetchProduct(page, productId)
    expect(data.sku).toBe(uniqueSku)
    expect(data.name).toBe(testData.name)
    expect(data.description).toBe('<p>API test description</p>')
  })
})

test.describe('Product Field Validation - Edit Mode Fields', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await openDashboard(page)
  })

  test('should save shop settings when editing product', async ({ page }) => {
    const testData = generateCompleteProductData()
    const productId = await createAndOpenEdit(page, testData.name)

    // Shop visibility toggle
    await page.getByRole('switch', { name: 'Show in Shop' }).click()

    // Shop description
    await page.locator('textarea[name="shop_description"]').fill('Shop-specific description')

    // Featured toggle
    await page.getByRole('switch', { name: 'Featured Item' }).click()

    await saveChanges(page)

    const saved = await fetchProduct(page, productId)
    expect(saved.shop_visible).toBe(true)
    expect(saved.shop_description).toBe('Shop-specific description')
    expect(saved.is_featured).toBe(true)
  })

  test('should save featured fields when is_featured enabled', async ({ page }) => {
    const testData = generateCompleteProductData()
    const productId = await createAndOpenEdit(page, testData.name)

    // Enable featured: its title and backstory fields appear
    await page.getByRole('switch', { name: 'Featured Item' }).click()
    await page.locator('input[name="feature_title"]').fill('Ember the Ancient')
    await page
      .locator('textarea[name="backstory"]')
      .fill('An ancient dragon awakened from eternal slumber...')

    await saveChanges(page)

    const saved = await fetchProduct(page, productId)
    expect(saved.is_featured).toBe(true)
    expect(saved.feature_title).toBe('Ember the Ancient')
    expect(saved.backstory).toBe('An ancient dragon awakened from eternal slumber...')
  })
})

test.describe('Product Navigation', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not running on port 8000')
    await openDashboard(page)
  })

  test('should navigate to products page from dashboard', async ({ page }) => {
    await page.goto('/dashboard')

    await page.getByRole('navigation').getByRole('link', { name: 'Products', exact: true }).click()
    await expect(page).toHaveURL(/\/products$/)
    await expect(page.getByRole('heading', { level: 2, name: 'Products', exact: true })).toBeVisible()
  })

  test('should require authentication for products page', async ({ page }) => {
    // Logout and wait for redirect to login page
    await page.goto('/logout')
    await page.waitForURL(/\/login/, { timeout: 10000 })

    // Now try to access protected route
    await page.goto('/products')
    await expect(page).toHaveURL(/\/login/)
  })
})
