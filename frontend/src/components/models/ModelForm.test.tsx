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
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'

/*
 * This file builds a genuine memory router, so it needs the real module rather
 * than the stub `src/test/setup.ts` installs for every other test. The stub
 * exists because importing the router cost every test file in the suite ~7s of
 * setup; paying it here, in the two files that cannot do without it, is the
 * trade.
 */
vi.unmock('@tanstack/react-router')
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
import { pricingApi } from '@/lib/api/pricing'
import { updateModel, type ModelDetail } from '@/lib/api/models'

vi.mock('@/lib/api/models', async (importOriginal) => ({
  inferModelFileType: (await importOriginal<typeof import('@/lib/api/models')>()).inferModelFileType,
  createModel: vi.fn(),
  updateModel: vi.fn(),
  listModels: vi.fn(),
  parse3mfFile: vi.fn(),
  uploadModelFile: vi.fn(),
}))

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: { getModelCostProfile: vi.fn() },
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
  plates: [],
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

function renderModelForm(node: ReactNode = <ModelForm mode="create" />) {
  const queryClient = createTestQueryClient()
  const rootRoute = createRootRoute()
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: () => node,
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

  it('shows a review of parsed values and pre-fills the form once applied', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 125,
      filament_weight_grams: 15.5,
      plate_count: 1,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: true,
      plates: [{ index: 1, print_time_minutes: 125, filament_weight_grams: 15.5, object_count: 2 }],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile())

    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    // The parsed values are shown for review before touching the form.
    await screen.findByText(/print time: 2h 5m/i)
    // Items per run are the objects on the plate, and the maker confirms them (T066).
    const items = screen.getByLabelText(/how many finished items does this plate make/i)
    expect(items).toHaveValue(2)
    screen.getByText(/2 objects on this plate in the file\. per item: 1h 3m · 7\.75g/i)
    const hoursField = screen.getByLabelText('Plate Print Time')
    const minutesField = screen.getByLabelText('')
    const platesField = screen.getByLabelText('Items per Plate')
    expect(hoursField).toHaveValue(null)
    expect(platesField).toHaveValue(1) // schema default, unrelated to the parse result

    await userEvent.click(screen.getByRole('button', { name: /apply to form/i }))

    await waitFor(() => expect(hoursField).toHaveValue(2)) // 125 min -> 2h 5m
    expect(minutesField).toHaveValue(5)
    expect(platesField).toHaveValue(2)
  })

  it('lets the maker select which plates to combine from a multi-plate file', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 60,
      filament_weight_grams: 10,
      plate_count: 3,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
      plates: [
        { index: 1, print_time_minutes: 60, filament_weight_grams: 10, object_count: 1 },
        { index: 2, print_time_minutes: 30, filament_weight_grams: 5, object_count: 1 },
        { index: 3, print_time_minutes: 15, filament_weight_grams: 2, object_count: 2 },
      ],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile())
    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    // All 3 plates are listed and selected by default; combined values sum all of them.
    await screen.findByText(/plate 1: 1h · 10g/i)
    screen.getByText(/plate 2: 30m · 5g/i)
    screen.getByText(/plate 3: 15m · 2g/i)
    await screen.findByText(/combined print time: 1h 45m/i) // 60+30+15 = 105 min
    screen.getByText(/combined filament weight: 17g/i) // 10+5+2
    const items = screen.getByLabelText(/how many finished items do these plates make/i)
    expect(items).toHaveValue(4) // the objects, not the 3 plates

    // Deselecting plate 3 recomputes the combined totals from the remaining selection.
    const plate3Row = screen.getByText(/plate 3: 15m · 2g/i).closest('label')
    await userEvent.click(within(plate3Row!).getByRole('checkbox'))

    await screen.findByText(/combined print time: 1h 30m/i) // 60+30
    screen.getByText(/combined filament weight: 15g/i) // 10+5
    expect(items).toHaveValue(2) // the default follows the selection

    await userEvent.click(screen.getByRole('button', { name: /apply to form/i }))

    const hoursField = screen.getByLabelText('Plate Print Time')
    const minutesField = screen.getByLabelText('')
    const platesField = screen.getByLabelText('Items per Plate')
    await waitFor(() => expect(hoursField).toHaveValue(1))
    expect(minutesField).toHaveValue(30)
    expect(platesField).toHaveValue(2)
  })

  it('applies the items the maker enters, not the object count, when they differ', async () => {
    // Two plates, one object each: a body and its base make ONE item.
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 90,
      filament_weight_grams: 30,
      plate_count: 2,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
      plates: [
        { index: 1, print_time_minutes: 60, filament_weight_grams: 20, object_count: 1 },
        { index: 2, print_time_minutes: 30, filament_weight_grams: 10, object_count: 1 },
      ],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), makeThreeMfFile())
    const items = await screen.findByLabelText(/how many finished items do these plates make/i)
    expect(items).toHaveValue(2)
    await userEvent.clear(items)
    await userEvent.type(items, '1')
    screen.getByText(/per item: 1h 30m · 30g/i)

    await userEvent.click(screen.getByRole('button', { name: /apply to form/i }))
    await waitFor(() => expect(screen.getByLabelText('Items per Plate')).toHaveValue(1))
  })

  it('asks for the items when the file does not list its objects, and leaves the field alone if blank', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 60,
      filament_weight_grams: 10,
      plate_count: 1,
      source_plate_index: 1,
      slicer_detected: 'prusaslicer',
      thumbnail_available: false,
      plates: [],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), makeThreeMfFile())
    const items = await screen.findByLabelText(/how many finished items does this plate make/i)
    expect(items).toHaveValue(null)
    screen.getByText(/doesn't say how many objects it prints/i)

    await userEvent.click(screen.getByRole('button', { name: /apply to form/i }))
    await waitFor(() => expect(screen.getByLabelText('Plate Print Time')).toHaveValue(1))
    expect(screen.getByLabelText('Items per Plate')).toHaveValue(1) // schema default, untouched
  })

  it('refuses to apply an item count that is not a whole number', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 60,
      filament_weight_grams: 10,
      plate_count: 1,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
      plates: [{ index: 1, print_time_minutes: 60, filament_weight_grams: 10, object_count: 2 }],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), makeThreeMfFile())
    const items = await screen.findByLabelText(/how many finished items/i)
    await userEvent.clear(items)
    await userEvent.type(items, '0')
    expect(screen.getByRole('button', { name: /apply to form/i })).toBeDisabled()
  })

  it('hands the BOM step the total and the grams of each filament', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 60,
      filament_weight_grams: 84,
      plate_count: 1,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
      plates: [
        {
          index: 1,
          print_time_minutes: 60,
          filament_weight_grams: 84,
          object_count: 4,
          filaments: [
            { type: 'PLA', color: '#FF0000', grams: 60 },
            { type: 'PLA', color: '#000000', grams: 24 },
          ],
        },
      ],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), makeThreeMfFile())
    await screen.findByText(/filament weight: 84g \(PLA #FF0000 60g, PLA #000000 24g\)/i)
    await userEvent.click(screen.getByRole('button', { name: /apply to form/i }))
    await userEvent.type(screen.getByLabelText('Name'), 'Two-tone dragon')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    await waitFor(() => expect(mockCreateModel).toHaveBeenCalledTimes(1))
    await waitFor(() =>
      expect(JSON.parse(sessionStorage.getItem('model-weight-suggestion:model-123')!)).toEqual({
        total: 84,
        filaments: [
          { type: 'PLA', color: '#FF0000', grams: 60 },
          { type: 'PLA', color: '#000000', grams: 24 },
        ],
      })
    )
    sessionStorage.clear()
  })

  it('shows a hint to slice the file first when nothing could be parsed', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: null,
      filament_weight_grams: null,
      plate_count: null,
      source_plate_index: null,
      slicer_detected: null,
      thumbnail_available: false,
      plates: [],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const fileInput = await screen.findByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile('fusion-export.3mf'))

    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))

    await screen.findByText(/no print data found/i)
    expect(screen.getByText(/fusion 360/i)).toBeInTheDocument()
    expect(screen.getByText(/bambu studio, orcaslicer, or prusaslicer/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /apply to form/i })).not.toBeInTheDocument()
  })

  it('does not overwrite a field the maker already edited before applying', async () => {
    mockParse3mfFile.mockResolvedValue({
      print_time_minutes: 125,
      filament_weight_grams: null,
      plate_count: 1,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
      plates: [{ index: 1, print_time_minutes: 125, filament_weight_grams: null, object_count: 4 }],
    } satisfies ThreeMFParseResponse)

    renderModelForm()

    const platesField = await screen.findByLabelText('Items per Plate')
    await userEvent.clear(platesField)
    await userEvent.type(platesField, '3')

    const fileInput = screen.getByLabelText(/auto-fill from \.3mf/i)
    await userEvent.upload(fileInput, makeThreeMfFile())

    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))
    await userEvent.click(await screen.findByRole('button', { name: /apply to form/i }))

    // The maker's manually-entered value survives applying the parse result.
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
      plates: [],
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

describe('ModelForm - files kept on the model (spec 004, FR-001, FR-005)', () => {
  const MODEL = {
    id: 'model-1',
    sku: 'MOD-001',
    name: 'Dragon',
    labor_hours: '0',
    overhead_percentage: '0',
    is_active: true,
    prints_per_plate: 1,
    units_in_stock: 0,
  } as unknown as ModelDetail

  beforeEach(() => {
    vi.clearAllMocks()
    mockListModels.mockResolvedValue({ models: [], total: 0, skip: 0, limit: 500 })
    mockListDesigners.mockResolvedValue({ designers: [], total: 0 })
    mockGetNextSKU.mockResolvedValue({ next_sku: 'MOD-001', highest_existing: 0 })
    mockCreateModel.mockResolvedValue({ id: 'model-123' })
    ;(updateModel as Mock).mockResolvedValue({ id: 'model-1' })
    ;(pricingApi.getModelCostProfile as Mock).mockResolvedValue({ origins: [] })
    mockUploadModelFile.mockResolvedValue({ id: 'file-1' })
    mockParse3mfFile.mockResolvedValue(ALL_NULL_PARSE_RESULT)
  })

  const stl = () => new File([new Uint8Array([1])], 'part.stl', { type: 'model/stl' })

  it('uploads the chosen source file after the model is created', async () => {
    renderModelForm()
    const file = stl()
    await userEvent.upload(await screen.findByLabelText(/model files/i), file)
    await userEvent.type(screen.getByLabelText('Name'), 'Dragon')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    await waitFor(() =>
      expect(mockUploadModelFile).toHaveBeenCalledWith('model-123', file, 'source_stl'),
    )
    expect(mockCreateModel.mock.invocationCallOrder[0]).toBeLessThan(
      mockUploadModelFile.mock.invocationCallOrder[0],
    )
  })

  it('uploads the chosen source file after an edit is saved', async () => {
    renderModelForm(<ModelForm mode="edit" model={MODEL} />)
    const file = stl()
    await userEvent.upload(await screen.findByLabelText(/model files/i), file)
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() =>
      expect(mockUploadModelFile).toHaveBeenCalledWith('model-1', file, 'source_stl'),
    )
  })

  it('takes several files of every kind and uploads them one after another', async () => {
    const order: string[] = []
    let release: () => void = () => {}
    mockUploadModelFile.mockImplementation((_id: string, file: File) => {
      order.push(`start ${file.name}`)
      return new Promise((resolve) => {
        release = () => {
          order.push(`end ${file.name}`)
          resolve({ id: file.name })
        }
      })
    })
    renderModelForm()
    const part = stl()
    const plate = new File([new Uint8Array([1])], 'plate.gcode.3mf')
    const gcode = new File([new Uint8Array([1])], 'plate.gcode')
    await userEvent.upload(await screen.findByLabelText(/model files/i), [part, plate, gcode])
    expect(screen.queryByText(/is a sliced plate/)).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'Dragon')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    for (const name of ['part.stl', 'plate.gcode.3mf', 'plate.gcode']) {
      await waitFor(() => expect(order.at(-1)).toBe(`start ${name}`))
      release()
    }
    expect(order).toEqual([
      'start part.stl', 'end part.stl',
      'start plate.gcode.3mf', 'end plate.gcode.3mf',
      'start plate.gcode', 'end plate.gcode',
    ])
    expect(mockUploadModelFile).toHaveBeenNthCalledWith(1, 'model-123', part, 'source_stl')
    expect(mockUploadModelFile).toHaveBeenNthCalledWith(2, 'model-123', plate, 'gcode')
    expect(mockUploadModelFile).toHaveBeenNthCalledWith(3, 'model-123', gcode, 'gcode')
  })

  it('warns when the source file chosen is a sliced plate', async () => {
    renderModelForm()
    const sliced = new File([new Uint8Array([1])], 'plate.gcode.3mf')
    await userEvent.upload(await screen.findByLabelText(/model files/i), sliced)
    expect(screen.getByText(/is a sliced plate/)).toBeInTheDocument()
  })

  it('offers the auto-fill on edit and keeps its file by default', async () => {
    renderModelForm(<ModelForm mode="edit" model={MODEL} />)
    const file = makeThreeMfFile()
    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), file)
    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('checkbox', { name: 'Keep this file on the model' })).toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() =>
      expect(mockUploadModelFile).toHaveBeenCalledWith('model-1', file, 'source_3mf'),
    )
  })

  it('discards the auto-fill file when "Keep this file on the model" is unchecked', async () => {
    renderModelForm()
    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), makeThreeMfFile())
    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Keep this file on the model' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Dragon')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    await waitFor(() => expect(mockCreateModel).toHaveBeenCalledTimes(1))
    expect(mockUploadModelFile).not.toHaveBeenCalled()
  })

  it('keeps a sliced auto-fill file as G-code, its print file', async () => {
    renderModelForm()
    const sliced = new File([new Uint8Array([1])], 'plate.gcode.3mf')
    await userEvent.upload(await screen.findByLabelText(/auto-fill from \.3mf/i), sliced)
    await waitFor(() => expect(mockParse3mfFile).toHaveBeenCalledTimes(1))
    await userEvent.type(screen.getByLabelText('Name'), 'Dragon')
    await userEvent.click(screen.getByRole('button', { name: /create model/i }))

    await waitFor(() =>
      expect(mockUploadModelFile).toHaveBeenCalledWith('model-123', sliced, 'gcode'),
    )
  })
})

describe('ModelForm - an observed figure is read-only (T262)', () => {
  const MODEL = {
    id: 'model-1',
    sku: 'MOD-001',
    name: 'Dragon',
    labor_hours: '0',
    overhead_percentage: '0',
    is_active: true,
    print_time_minutes: 570,
    prints_per_plate: 4,
    units_in_stock: 0,
  } as unknown as ModelDetail

  function origin(field_name: string, source: string, editable: boolean) {
    return { field_name, source, as_of: '2026-10-24', is_stale: false, editable }
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockListModels.mockResolvedValue({ models: [], total: 0, skip: 0, limit: 500 })
    mockListDesigners.mockResolvedValue({ designers: [], total: 0 })
    ;(updateModel as Mock).mockResolvedValue({ id: 'model-1' })
  })

  it('locks a print time telemetry observed and names its origin', async () => {
    ;(pricingApi.getModelCostProfile as Mock).mockResolvedValue({
      origins: [
        origin('print_time_minutes', 'observed', false),
        origin('prints_per_plate', 'measured', true),
      ],
    })
    renderModelForm(<ModelForm mode="edit" model={MODEL} />)

    const minutes = await screen.findByLabelText('Plate print time minutes')
    await waitFor(() => expect(minutes).toBeDisabled())
    expect(screen.getByText(/observed/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Items per Plate/)).toBeEnabled()
  })

  it('leaves the observed print time out of the save', async () => {
    ;(pricingApi.getModelCostProfile as Mock).mockResolvedValue({
      origins: [origin('print_time_minutes', 'observed', false)],
    })
    const user = userEvent.setup()
    renderModelForm(<ModelForm mode="edit" model={MODEL} />)

    await waitFor(() =>
      expect(screen.getByLabelText('Plate print time minutes')).toBeDisabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => expect(updateModel).toHaveBeenCalled())
    const [, body] = (updateModel as Mock).mock.calls[0]
    expect(body.print_time_minutes).toBeUndefined()
    expect(body.prints_per_plate).toBe(4)
  })
})
