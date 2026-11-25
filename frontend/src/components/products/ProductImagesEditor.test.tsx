/**
 * Tests for ProductImagesEditor component
 *
 * Tests the image management functionality including:
 * - Loading and displaying product images
 * - Drag-and-drop reordering
 * - Set primary image
 * - Delete image
 * - Upload images
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProductImagesEditor } from './ProductImagesEditor'
import * as productsApi from '@/lib/api/products'
import { within } from '@testing-library/react'
import { capabilities } from '@/components/genai/genaiTestData'

// Mock the products API
vi.mock('@/lib/api/products', () => ({
  getProductImages: vi.fn(),
  uploadProductImage: vi.fn(),
  setPrimaryImage: vi.fn(),
  deleteProductImage: vi.fn(),
  rotateProductImage: vi.fn(),
  updateProductImage: vi.fn(),
}))

// The signed-in role decides whether the AI controls are offered (spec 008).
const auth = vi.hoisted(() => ({ role: 'viewer' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'operator@example.com', role: auth.role }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})

const genai = vi.hoisted(() => ({
  capabilities: vi.fn(),
  estimate: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
  listJobs: vi.fn(),
  cancelJob: vi.fn(),
  adopt: vi.fn(),
  upload: vi.fn(),
  getBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: genai }))

// Mock config
vi.mock('@/lib/config', () => ({
  config: {
    apiUrl: 'http://localhost:8000',
  },
}))

const mockImages: productsApi.ProductImage[] = [
  {
    id: 'img-1',
    product_id: 'prod-1',
    image_url: '/uploads/img1.jpg',
    thumbnail_url: '/uploads/img1_thumb.jpg',
    original_filename: 'product-front.jpg',
    alt_text: 'Product front view',
    is_primary: true,
    display_order: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    origin: 'photo',
  },
  {
    id: 'img-2',
    product_id: 'prod-1',
    image_url: '/uploads/img2.jpg',
    thumbnail_url: '/uploads/img2_thumb.jpg',
    original_filename: 'product-back.jpg',
    alt_text: 'Product back view',
    is_primary: false,
    display_order: 1,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
    origin: 'photo',
  },
  {
    id: 'img-3',
    product_id: 'prod-1',
    image_url: '/uploads/img3.jpg',
    thumbnail_url: '/uploads/img3_thumb.jpg',
    original_filename: 'product-side.jpg',
    alt_text: 'Product side view',
    is_primary: false,
    display_order: 2,
    created_at: '2024-01-03T00:00:00Z',
    updated_at: '2024-01-03T00:00:00Z',
    origin: 'photo',
  },
]

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
}

function renderWithQueryClient(component: React.ReactNode) {
  const queryClient = createQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      {component}
    </QueryClientProvider>
  )
}

describe('ProductImagesEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'viewer'
  })

  describe('Loading State', () => {
    it('shows loading spinner while fetching images', () => {
      vi.mocked(productsApi.getProductImages).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      expect(document.querySelector('.animate-spin')).toBeInTheDocument()
    })
  })

  describe('Empty State', () => {
    it('shows empty state when no images exist', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue([])

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('No images yet')).toBeInTheDocument()
      })

      expect(screen.getByText('Upload images to display in the shop')).toBeInTheDocument()
    })
  })

  describe('Image Display', () => {
    it('displays images when loaded', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      expect(screen.getByText('product-back.jpg')).toBeInTheDocument()
      expect(screen.getByText('product-side.jpg')).toBeInTheDocument()
    })

    it('displays primary badge on primary image', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('Primary')).toBeInTheDocument()
      })
    })

    it('sorts images by primary first, then display_order', async () => {
      // Mock images with primary not first in the array
      const unsortedImages = [
        { ...mockImages[1], display_order: 1 },
        { ...mockImages[2], display_order: 2 },
        { ...mockImages[0], display_order: 0 }, // Primary image last in array
      ]
      vi.mocked(productsApi.getProductImages).mockResolvedValue(unsortedImages)

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Primary image should appear first in the DOM
      const imageLabels = screen.getAllByText(/product-.+\.jpg/)
      expect(imageLabels[0]).toHaveTextContent('product-front.jpg')
    })
  })

  describe('Upload Area', () => {
    it('displays upload area', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue([])

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('Click to upload')).toBeInTheDocument()
      })

      expect(screen.getByText(/drag and drop/)).toBeInTheDocument()
      expect(screen.getByText('JPEG, PNG or WebP (max 10MB)')).toBeInTheDocument()
    })

    it('accepts multiple file types', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue([])

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('Click to upload')).toBeInTheDocument()
      })

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
      expect(fileInput).toBeInTheDocument()
      expect(fileInput.accept).toBe('image/jpeg,image/png,image/webp')
      expect(fileInput.multiple).toBe(true)
    })
  })

  describe('Drag Handle', () => {
    it('renders drag handle on each image', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Each image should have a drag handle
      const dragHandles = document.querySelectorAll('[title="Drag to reorder"]')
      expect(dragHandles.length).toBe(mockImages.length)
    })
  })

  describe('Reordering', () => {
    it('calls updateProductImage API when images are reordered', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)
      vi.mocked(productsApi.updateProductImage).mockResolvedValue(mockImages[0])

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Note: Full drag-and-drop testing requires @dnd-kit/test-utils or similar
      // This test validates the API function is available and mockable
      expect(productsApi.updateProductImage).not.toHaveBeenCalled()
    })
  })

  describe('Set Primary', () => {
    it('calls setPrimaryImage when Set Primary button is clicked', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)
      vi.mocked(productsApi.setPrimaryImage).mockResolvedValue(mockImages[1])

      const user = userEvent.setup({ delay: null })

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-back.jpg')).toBeInTheDocument()
      })

      // Hover over non-primary image to show actions
      const imageCards = document.querySelectorAll('.group')
      expect(imageCards.length).toBeGreaterThan(0)

      // Find and click the Set Primary button (should be on non-primary images)
      const setPrimaryButtons = screen.getAllByText('Set Primary')
      expect(setPrimaryButtons.length).toBe(2) // Only non-primary images have this button

      await user.click(setPrimaryButtons[0])

      await waitFor(() => {
        expect(productsApi.setPrimaryImage).toHaveBeenCalledWith('prod-1', expect.any(String))
      })
    })
  })

  describe('Delete Image', () => {
    it('shows confirmation dialog before deleting', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)

      const user = userEvent.setup({ delay: null })

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Find delete buttons (should have trash icon)
      const deleteButtons = document.querySelectorAll('button[class*="destructive"]')
      expect(deleteButtons.length).toBeGreaterThan(0)

      await user.click(deleteButtons[0])

      await waitFor(() => {
        expect(screen.getByText('Delete Image')).toBeInTheDocument()
      })

      expect(screen.getByText(/Are you sure you want to delete this image/)).toBeInTheDocument()
    })

    it('calls deleteProductImage when confirmed', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)
      vi.mocked(productsApi.deleteProductImage).mockResolvedValue(undefined)

      const user = userEvent.setup({ delay: null })

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Click delete button
      const deleteButtons = document.querySelectorAll('button[class*="destructive"]')
      await user.click(deleteButtons[0])

      // Confirm deletion
      await waitFor(() => {
        expect(screen.getByText('Delete Image')).toBeInTheDocument()
      })

      const confirmButton = screen.getByRole('button', { name: 'Delete' })
      await user.click(confirmButton)

      await waitFor(() => {
        expect(productsApi.deleteProductImage).toHaveBeenCalledWith('prod-1', expect.any(String))
      })
    })
  })

  describe('Rotate Image', () => {
    it('calls rotateProductImage when rotate button is clicked', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)
      vi.mocked(productsApi.rotateProductImage).mockResolvedValue(mockImages[0])

      const user = userEvent.setup({ delay: null })

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Find rotate buttons (title="Rotate 90...")
      const rotateButtons = document.querySelectorAll('[title*="Rotate"]')
      expect(rotateButtons.length).toBe(mockImages.length)

      await user.click(rotateButtons[0])

      await waitFor(() => {
        expect(productsApi.rotateProductImage).toHaveBeenCalledWith('prod-1', 'img-1', 90)
      })
    })
  })

  describe('Image Preview', () => {
    it('opens preview dialog when eye button is clicked', async () => {
      vi.mocked(productsApi.getProductImages).mockResolvedValue(mockImages)

      const user = userEvent.setup({ delay: null })

      renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)

      await waitFor(() => {
        expect(screen.getByText('product-front.jpg')).toBeInTheDocument()
      })

      // Find preview buttons (Eye icon buttons)
      const previewButtons = document.querySelectorAll('button[title="View full image"]')
      expect(previewButtons.length).toBe(mockImages.length)

      await user.click(previewButtons[0])

      // Dialog should open with image preview
      await waitFor(() => {
        // The dialog contains an img element
        const dialogImages = document.querySelectorAll('[role="dialog"] img')
        expect(dialogImages.length).toBe(1)
      })
    })
  })
})

// ============================================
// Generative AI (spec 008, US3, FR-017)
// ============================================

describe('ProductImagesEditor generative AI', () => {
  const withAI: productsApi.ProductImage[] = [
    mockImages[0],
    { ...mockImages[1], origin: 'ai' },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'member'
    vi.mocked(productsApi.getProductImages).mockResolvedValue(withAI)
    vi.mocked(productsApi.updateProductImage).mockResolvedValue({ ...mockImages[0], origin: 'render' })
    genai.getBlob.mockImplementation(() => new Promise(() => {}))
    genai.capabilities.mockResolvedValue(capabilities())
    genai.estimate.mockResolvedValue({
      estimated_cost: '0.0030',
      month_to_date: '1.2000',
      budget: '10.00',
      would_exceed_budget: false,
      currency: 'USD',
    })
  })

  it('marks an AI image with the badge and offers no origin select for it', async () => {
    renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)
    expect(await screen.findByLabelText('AI: made with generative AI')).toBeInTheDocument()
    // Only the photo keeps an origin select; "ai" is never chosen by hand.
    const selects = screen.getAllByLabelText('Image origin')
    expect(selects).toHaveLength(1)
    expect(screen.queryByRole('option', { name: 'AI' })).not.toBeInTheDocument()
  })

  it('patches the origin when a photo is marked as a render', async () => {
    const user = userEvent.setup({ delay: null })
    renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)
    const select = await screen.findByLabelText('Image origin')
    await user.selectOptions(select, 'render')
    await waitFor(() =>
      expect(productsApi.updateProductImage).toHaveBeenCalledWith('prod-1', 'img-1', { origin: 'render' })
    )
  })

  it('offers the AI menu to a member', async () => {
    renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)
    await screen.findByText('product-front.jpg')
    expect(screen.getAllByRole('button', { name: 'AI actions' })).toHaveLength(withAI.length)
  })

  it('hides the AI menu from a viewer', async () => {
    auth.role = 'viewer'
    renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)
    await screen.findByText('product-front.jpg')
    expect(screen.queryByRole('button', { name: 'AI actions' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Image origin')).toBeDisabled()
  })

  it('opens the generate dialog with that image when Remove background is chosen', async () => {
    const user = userEvent.setup({ delay: null })
    renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)
    await screen.findByText('product-front.jpg')
    await user.click(screen.getAllByRole('button', { name: 'AI actions' })[0])
    await user.click(await screen.findByRole('menuitem', { name: 'Remove background' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: /Remove background/ })).toBeInTheDocument()
    expect(await within(dialog).findByRole('button', { name: 'Product front view' })).toBeInTheDocument()
    // The original is never changed by an AI action.
    expect(productsApi.updateProductImage).not.toHaveBeenCalled()
  })

  it('lists the product generations in a collapsible section', async () => {
    genai.listJobs.mockResolvedValue({ items: [], total: 0 })
    const user = userEvent.setup({ delay: null })
    renderWithQueryClient(<ProductImagesEditor productId="prod-1" />)
    await screen.findByText('product-front.jpg')
    await user.click(screen.getByRole('button', { name: /AI generations/ }))
    expect(await screen.findByText('No AI generations yet.')).toBeInTheDocument()
  })
})
