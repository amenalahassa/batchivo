/**
 * E2E Tests: Shop Visibility & Featured Products
 *
 * Tests the shop display functionality for products:
 * - Toggle shop visibility on/off
 * - Set shop description
 * - Toggle featured status
 * - Set feature title and backstory
 *
 * These settings live on the product edit page ("Shop Display Settings").
 */

import { type Page } from '@playwright/test'
import { test, expect } from '../../fixtures'
import { apiAs, isBackendAvailable } from '../../helpers'

const PRODUCT_DETAIL_URL = /\/products\/[0-9a-f-]{36}$/

// Generate unique test data
const generateTestProduct = () => ({
  sku: `SHOP-TEST-${Date.now()}`,
  name: `Shop Visibility Test ${Date.now()}`,
  description: 'Product for shop visibility E2E testing',
  shopDescription: 'Beautiful handcrafted item perfect for collectors',
  featureTitle: 'Featured Dragon of the Month',
  backstory: 'This rare dragon was discovered in the mystical forests...',
})

// Helper: Seed a test product through the API and return its ID
async function createTestProduct(page: Page, product: ReturnType<typeof generateTestProduct>): Promise<string> {
  const created = await (await apiAs(page)).post('/api/v1/products', {
    sku: product.sku,
    name: product.name,
    description: product.description,
  })
  return created.id
}

// Helper: Open the product edit page once its form holds the product
async function navigateToProductEdit(page: Page, productId: string, productName: string) {
  await page.goto(`/products/${productId}/edit`)
  await expect(page.locator('input[name="name"]')).toHaveValue(productName, { timeout: 10000 })
}

// Helper: Save the edit form and wait for the detail page
async function saveChanges(page: Page) {
  await page.getByRole('button', { name: 'Save Changes' }).click()
  await page.waitForURL(PRODUCT_DETAIL_URL, { timeout: 15000 })
}

const shopVisibleSwitch = (page: Page) => page.getByRole('switch', { name: 'Show in Shop' })
const featuredSwitch = (page: Page) => page.getByRole('switch', { name: 'Featured Item' })

test.describe('Shop Visibility Toggle', () => {
  let testProduct: ReturnType<typeof generateTestProduct>
  let productId: string

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    testProduct = generateTestProduct()
    productId = await createTestProduct(page, testProduct)
  })

  test('should toggle shop visibility ON', async ({ page }) => {
    await navigateToProductEdit(page, productId, testProduct.name)

    // A new product is not in the shop
    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'unchecked')
    await shopVisibleSwitch(page).click()
    await saveChanges(page)

    // Go back to edit and verify
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'checked')
  })

  test('should toggle shop visibility OFF', async ({ page }) => {
    // First enable shop visibility
    await navigateToProductEdit(page, productId, testProduct.name)
    await shopVisibleSwitch(page).click()
    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'checked')
    await saveChanges(page)

    // Now disable it
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'checked')
    await shopVisibleSwitch(page).click()
    await saveChanges(page)

    // Verify it's off
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'unchecked')
  })

  test('should set shop description when visible', async ({ page }) => {
    await navigateToProductEdit(page, productId, testProduct.name)

    // Enable shop visibility
    await shopVisibleSwitch(page).click()

    // Fill shop description
    const shopDescriptionInput = page.locator('textarea[name="shop_description"]')
    await shopDescriptionInput.fill(testProduct.shopDescription)

    await saveChanges(page)

    // Verify
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'checked')
    await expect(shopDescriptionInput).toHaveValue(testProduct.shopDescription)
  })
})

test.describe('Featured Product Toggle', () => {
  let testProduct: ReturnType<typeof generateTestProduct>
  let productId: string

  test.beforeEach(async ({ page }) => {
    test.skip(!(await isBackendAvailable()), 'Backend API not available')
    testProduct = generateTestProduct()
    productId = await createTestProduct(page, testProduct)
  })

  test('should toggle featured status ON', async ({ page }) => {
    await navigateToProductEdit(page, productId, testProduct.name)

    // Enable featured
    await expect(featuredSwitch(page)).toHaveAttribute('data-state', 'unchecked')
    await featuredSwitch(page).click()
    await saveChanges(page)

    // Verify
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(featuredSwitch(page)).toHaveAttribute('data-state', 'checked')
  })

  test('should set feature title when featured', async ({ page }) => {
    await navigateToProductEdit(page, productId, testProduct.name)

    // The feature fields only appear once the product is featured
    const featureTitleInput = page.locator('input[name="feature_title"]')
    await expect(featureTitleInput).toHaveCount(0)
    await featuredSwitch(page).click()

    await featureTitleInput.fill(testProduct.featureTitle)
    await saveChanges(page)

    // Verify
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(featureTitleInput).toHaveValue(testProduct.featureTitle)
  })

  test('should set backstory when featured', async ({ page }) => {
    await navigateToProductEdit(page, productId, testProduct.name)

    // Enable featured
    await featuredSwitch(page).click()

    // Fill backstory
    const backstoryInput = page.locator('textarea[name="backstory"]')
    await backstoryInput.fill(testProduct.backstory)
    await saveChanges(page)

    // Verify
    await navigateToProductEdit(page, productId, testProduct.name)
    await expect(backstoryInput).toHaveValue(testProduct.backstory)
  })

  test('should enable both shop visibility and featured status', async ({ page }) => {
    await navigateToProductEdit(page, productId, testProduct.name)

    // Enable shop visibility and featured
    await shopVisibleSwitch(page).click()
    await featuredSwitch(page).click()

    // Fill all fields
    await page.locator('textarea[name="shop_description"]').fill(testProduct.shopDescription)
    await page.locator('input[name="feature_title"]').fill(testProduct.featureTitle)
    await page.locator('textarea[name="backstory"]').fill(testProduct.backstory)

    await saveChanges(page)

    // Verify all fields saved
    await navigateToProductEdit(page, productId, testProduct.name)

    await expect(shopVisibleSwitch(page)).toHaveAttribute('data-state', 'checked')
    await expect(featuredSwitch(page)).toHaveAttribute('data-state', 'checked')
    await expect(page.locator('textarea[name="shop_description"]')).toHaveValue(testProduct.shopDescription)
    await expect(page.locator('input[name="feature_title"]')).toHaveValue(testProduct.featureTitle)
    await expect(page.locator('textarea[name="backstory"]')).toHaveValue(testProduct.backstory)
  })
})
