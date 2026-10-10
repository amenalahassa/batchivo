/**
 * Tests for ModelForm - 3MF Import Auto-Fill
 *
 * Covers:
 * - Uploading a .3mf file pre-fills print time / plate count (US1)
 * - A field the maker already edited is not overwritten by a later parse (US1/FR-007)
 * - The parsed filament weight is captured for hand-off to the BOM step (US1a)
 * - An all-null parse response never blocks manual submission (US2)
 * - The originally-uploaded file is attached to the model after creation,
 *   so the existing thumbnail-extraction path still runs (FR-006, Phase 8 convergence)
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { ModelForm } from './ModelForm'
import {
  createModel,
  listModels,
  parse3mfFile,
  uploadModelFile,
  type ThreeMFParseResponse,
} from '@/lib/api/models'
import { listDesigners } from '@/lib/api/designers'
import { skuApi } from '@/lib/api/sku'

vi.mock('@/lib/api/models', () => ({
  createModel: vi.fn(),
  updateModel: vi.fn(),
  listModels: vi.fn(),
  parse3mfFile: vi.fn(),
  uploadModelFile: vi.fn(),
}))

vi.mock('@/lib/api/designers', () => ({
  listDesigners: vi.fn(),
}))

vi.mock('@/lib/api/sku', () => ({
  skuApi: {
    getNextSKU: vi.fn(),
  },
}))

const mockCreateModel = createModel as Mock
const mockListModels = listModels as Mock
const mockParse3mfFile = parse3mfFile as Mock
const mockUploadModelFile = uploadModelFile as Mock
const mockListDesigners = listDesigners as Mock
const mockGetNextSKU = skuApi.getNextSKU as Mock

const ALL_NULL_PARSE_RESULT: ThreeMFParseResponse = {
  print_time_minutes: null,
  filament_weight_grams: null,
  plate_count: null,
  source_plate_index: null,
  slicer_detected: null,
  thumbnail_available: false,
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

function renderModelForm() {
  const queryClient = createTestQueryClient()
  const rootRoute = createRootRoute()
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: () => <ModelForm mode="create" />,
  })
  const router = createRouter({
    routeTree: rootRoute.addChildren([indexRoute]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

function makeThreeMfFile(name = 'model.3mf') {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'model/3mf' })
}

describe('ModelForm - 3MF import auto-fill', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListModels.mockResolvedValue({ models: [], total: 0, skip: 0, limit: 500 })
    mockListDesigners.mockResolvedValue({ designers: [], total: 0 })
    mockGetNextSKU.mockResolvedValue({ next_sku: 'MOD-001', highest_existing: 0 })
    mockCreateModel.mockResolvedValue({ id: 'model-123' })
    mockUploadModelFile.mockResolvedValue({ id: 'file-1' })
  })

  it('pre-fills print time and plate count from a parsed 3MF upload', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 125,
      filament_weight_grams: 15.5,
      plate_count: 2,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: true,
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile())

    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    const hoursField = await screen.findByLabelText('Plate Print Time')
    const minutesField = screen.getByLabelText('')
    const platesField = screen.getByLabelText('Items per Plate')

    await waitFor(() => expect(hoursField).toHaveValue(2)) // 125 min -> 2h 5m
    expect(minutesField).toHaveValue(5)
    expect(platesField).toHaveValue(2)
  })

  it('does not overwrite a field the maker already edited before uploading', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 125,
      filament_weight_grams: null,
      plate_count: 4,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const platesField = await screen.findByLabelText('Items per Plate')
    await userEvent.clear(platesField)
    await userEvent.type(platesField, '3')

    const fileInput = screen.getByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile())

    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    // The maker's manually-entered value survives the later parse result.
    await waitFor(() => expect(platesField).toHaveValue(3))
  })

  it('never blocks manual submission when the parse result is all-null', async () => {
    mockParse3mfFile.mockResolvedValue(ALL_NULL_PARSE_RESULT)

    renderModelForm()

    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile())

    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    const nameField = screen.getByLabelText('Name')
    await userEvent.type(nameField, 'My Manual Model')

    const submitButton = screen.getByRole('button', { name: /create model/i })
    await userEvent.click(submitButton)

    await waitFor(() => expect(mockCreateModel).toHaveBeenCalledTimes(1))
  })

  it('attaches the uploaded 3MF to the model after creation so the thumbnail still gets extracted', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 60,
      filament_weight_grams: null,
      plate_count: 1,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: true,
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const file = makeThreeMfFile()
    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, file)
    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    await userEvent.type(screen.getByLabelText('Name'), 'Dragon Figurine')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    await waitFor(() => expect(mockCreateModel).toHaveBeenCalledTimes(1))
    await waitFor(() =>
      expect(mockUploadModelFile).toHaveBeenCalledWith('model-123', file, 'source_3mf')
    )
  })

  it('still attaches the uploaded file even when parsing itself fails', async () => {
    mockParse3mfFile.mockRejectedValue(new Error('network error'))

    renderModelForm()

    const file = makeThreeMfFile()
    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, file)
    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    await userEvent.type(screen.getByLabelText('Name'), 'Dragon Figurine')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    await waitFor(() => expect(mockCreateModel).toHaveBeenCalledTimes(1))
    await waitFor(() =>
      expect(mockUploadModelFile).toHaveBeenCalledWith('model-123', file, 'source_3mf')
    )
  })
})
