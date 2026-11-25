import { test, expect } from './fixtures'
import { apiAs, uniqueSuffix } from './helpers'

/**
 * Product-category management from the product detail page.
 *
 * Each test signs up a fresh tenant, so it seeds the product and category it
 * works on through the API.
 */
test.describe('Product Categories', () => {
  let productId = ''
  let productName = ''
  let categoryName = ''

  test.beforeEach(async ({ page }) => {
    const api = await apiAs(page)
    const suffix = uniqueSuffix()
    productName = `E2E Category Product ${suffix}`
    categoryName = `E2E Category ${suffix}`
    const product = await api.post('/api/v1/products', { sku: `E2E-CAT-${suffix}`, name: productName })
    productId = product.id
    await api.post('/api/v1/categories', { name: categoryName })
  })

  test('can view and manage product categories', async ({ page }) => {
    await page.goto('/products')
    await expect(page.getByRole('heading', { level: 2, name: 'Products', exact: true })).toBeVisible()

    // Open the product from the list
    await page.getByRole('row').filter({ hasText: productName }).getByRole('link', { name: productName }).click()
    await expect(page.getByRole('heading', { level: 1, name: productName })).toBeVisible({
      timeout: 10000,
    })

    // The Categories card offers "Add Category"
    await expect(page.getByText('No categories assigned')).toBeVisible()
    await page.getByRole('button', { name: 'Add Category' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByPlaceholder('Search categories...')).toBeVisible({ timeout: 10000 })

    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
  })

  test('can add a category to a product', async ({ page }) => {
    await page.goto(`/products/${productId}`)
    await expect(page.getByRole('heading', { level: 1, name: productName })).toBeVisible({
      timeout: 10000,
    })

    await page.getByRole('button', { name: 'Add Category' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    await dialog.getByRole('option', { name: categoryName }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5000 })

    // The category now shows as assigned, and is no longer offered
    await expect(page.getByText('No categories assigned')).not.toBeVisible()
    await expect(page.getByText(categoryName, { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Add Category' }).click()
    await expect(dialog.getByText('Product is already in all available categories')).toBeVisible()
  })
})
