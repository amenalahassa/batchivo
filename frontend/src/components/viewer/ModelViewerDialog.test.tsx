/**
 * The viewer dialog without WebGL (spec 004, T037; FR-020 to FR-023).
 *
 * The canvas and the worker are replaced: what is under test is what the
 * dialog decides to show and say.
 */
import { describe, expect, it, vi, beforeEach, type Mock } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import ModelViewerDialog from './ModelViewerDialog'
import { LOCAL_REFERENCE_TEXT, mismatches, NO_PLANNED_MACHINE, REDUCED_PREVIEW } from '@/lib/viewer/notices'
import { fetchModelFile, parseInWorker } from '@/lib/viewer/parseInWorker'
import { pricingApi } from '@/lib/api/pricing'
import { getPrinter } from '@/lib/api/printers'
import { getModelProductionDefaults, type ModelFile } from '@/lib/api/models'
import { listFileNotes } from '@/lib/api/modelFileNotes'
import { parseGcode } from '@/lib/viewer/gcode'
import { plainGcode } from '@/test/fixtures/modelFiles'

vi.mock('./ViewerCanvas', () => ({
  ViewerCanvas: ({ bed, children }: { bed: { x: number; y: number } | null; children: ReactNode }) => (
    <div data-testid="canvas" data-bed={bed ? `${bed.x}x${bed.y}` : 'none'}>
      {children}
    </div>
  ),
}))
vi.mock('./MeshView', () => ({ MeshView: () => <div data-testid="mesh" /> }))
vi.mock('./ToolpathView', () => ({ ToolpathView: () => <div data-testid="toolpath" /> }))
vi.mock('./NotePins', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./NotePins')>()),
  NotePins: () => null,
}))
vi.mock('@/lib/viewer/parseInWorker', () => ({ fetchModelFile: vi.fn(), parseInWorker: vi.fn() }))
vi.mock('@/lib/api/pricing', () => ({ pricingApi: { getModelCostProfile: vi.fn() } }))
vi.mock('@/lib/api/printers', () => ({ getPrinter: vi.fn() }))
vi.mock('@/lib/api/models', () => ({ getModelProductionDefaults: vi.fn() }))
vi.mock('@/lib/api/modelFileNotes', () => ({
  listFileNotes: vi.fn(),
  createFileNote: vi.fn(),
  updateFileNote: vi.fn(),
  carryFileNoteForward: vi.fn(),
}))

const FILE: ModelFile = {
  id: 'g1',
  model_id: 'm1',
  version_id: 'v1',
  file_type: 'gcode',
  file_location: 'uploaded',
  original_filename: 'plate.gcode',
  is_primary: false,
  is_sliced: true,
  uploaded_at: '2026-11-01T10:00:00Z',
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-01T10:00:00Z',
}

const A1 = { id: 'p1', name: 'Bambu A1', model: 'A1', bed_size_x_mm: 256, bed_size_y_mm: 256, nozzle_diameter_mm: 0.4 }

function renderDialog(file = FILE) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ModelViewerDialog modelId="m1" file={file} versions={[]} canWrite open onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

describe('ModelViewerDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(fetchModelFile as Mock).mockResolvedValue(new ArrayBuffer(8))
    ;(parseInWorker as Mock).mockResolvedValue({
      kind: 'toolpath',
      toolpath: parseGcode(plainGcode()),
      plates: [],
      plate: null,
      reduced: false,
    })
    ;(pricingApi.getModelCostProfile as Mock).mockResolvedValue({ origins: [], planned_printer_id: 'p1' })
    ;(getPrinter as Mock).mockResolvedValue(A1)
    ;(getModelProductionDefaults as Mock).mockResolvedValue({ bom_materials: [{ material_type_code: 'PLA' }] })
    ;(listFileNotes as Mock).mockResolvedValue([])
  })

  it('explains a local reference instead of opening it', async () => {
    renderDialog({ ...FILE, file_location: 'local_reference' })
    expect(await screen.findByText(LOCAL_REFERENCE_TEXT)).toBeInTheDocument()
    expect(fetchModelFile).not.toHaveBeenCalled()
  })

  it('draws the toolpath on the planned printer\'s bed, with a layer slider', async () => {
    renderDialog()
    expect(await screen.findByTestId('toolpath')).toBeInTheDocument()
    expect(await screen.findByTestId('canvas')).toHaveAttribute('data-bed', '256x256')
    expect(screen.getByRole('slider', { name: 'Layer' })).toBeInTheDocument()
    expect(screen.queryByText(NO_PLANNED_MACHINE)).not.toBeInTheDocument()
  })

  it('says when there is no planned machine', async () => {
    ;(pricingApi.getModelCostProfile as Mock).mockResolvedValue({ origins: [], planned_printer_id: null })
    renderDialog()
    expect(await screen.findByText(NO_PLANNED_MACHINE)).toBeInTheDocument()
  })

  it('states what the file was sliced for when it differs from the plan', async () => {
    ;(getPrinter as Mock).mockResolvedValue({ ...A1, name: 'Prusa MK4', model: 'MK4', nozzle_diameter_mm: 0.6 })
    ;(getModelProductionDefaults as Mock).mockResolvedValue({ bom_materials: [{ material_type_code: 'PETG' }] })
    renderDialog()
    expect(await screen.findByText('Sliced for Bambu Lab A1; the planned printer is Prusa MK4.')).toBeInTheDocument()
    expect(screen.getByText(/Sliced for PLA; the bill of materials uses PETG/)).toBeInTheDocument()
    expect(screen.getByText(/0.4 mm nozzle; the planned printer has 0.6 mm/)).toBeInTheDocument()
  })

  it('says when only a reduced preview is shown', async () => {
    ;(parseInWorker as Mock).mockResolvedValue({
      kind: 'mesh',
      mesh: { positions: new Float32Array(9), triangleCount: 1, reduced: true },
      reduced: true,
    })
    renderDialog({ ...FILE, original_filename: 'big.stl', file_type: 'source_stl', is_sliced: false })
    expect(await screen.findByTestId('mesh')).toBeInTheDocument()
    expect(screen.getByText(REDUCED_PREVIEW)).toBeInTheDocument()
  })

  it('offers the plate picker for a multi-plate file', async () => {
    ;(parseInWorker as Mock).mockResolvedValue({
      kind: 'toolpath',
      toolpath: parseGcode(plainGcode()),
      plates: [1, 2],
      plate: 1,
      reduced: false,
    })
    renderDialog({ ...FILE, original_filename: 'two.gcode.3mf' })
    expect(await screen.findByRole('combobox', { name: 'Plate' })).toBeInTheDocument()
  })
})

describe('mismatches', () => {
  it('finds nothing when the header matches the plan', () => {
    expect(mismatches({ printerModel: 'Bambu Lab A1', filamentType: 'PLA', nozzleDiameter: '0.4' }, A1, ['PLA'])).toEqual([])
  })

  it('tells an A1 mini from an A1', () => {
    expect(mismatches({ printerModel: 'Bambu Lab A1' }, { ...A1, name: 'Mini', model: 'A1 mini' }, [])).toHaveLength(1)
  })
})
