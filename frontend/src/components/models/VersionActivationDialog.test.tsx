/**
 * The activation review (spec 004, T033; FR-011, FR-012).
 */
import { describe, expect, it, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { VersionActivationDialog } from './VersionActivationDialog'
import { activateFileVersion, getActivationPreview } from '@/lib/api/modelFileVersions'
import type { ActivationPreview, FileVersion } from '@/types/model-file-version'

vi.mock('@/lib/api/modelFileVersions', () => ({
  getActivationPreview: vi.fn(),
  activateFileVersion: vi.fn(),
  listFileVersions: vi.fn(),
  createFileVersion: vi.fn(),
  updateFileVersion: vi.fn(),
}))

const VERSION: FileVersion = {
  id: 'v2',
  model_id: 'm1',
  sequence: 2,
  label: '2',
  note: 'thicker walls',
  is_active: false,
  print_file_id: 'f-print',
  created_by: null,
  created_at: '2026-11-01T10:00:00Z',
  files: [],
  has_measurable_file: true,
  open_note_count: 0,
}

const PREVIEW: ActivationPreview = {
  version_id: 'v2',
  print_file_id: 'f-print',
  dimension_file_id: 'f-stl',
  dimension_file_name: 'part_v2.stl',
  rows: [
    { field: 'print_time_minutes', target: 'model', current: '112', proposed: '224', selectable: true, reason: null, source_file_id: null },
    { field: 'prints_per_plate', target: 'model', current: '1', proposed: '2', selectable: true, reason: null, source_file_id: null },
    { field: 'weight_grams', target: 'model_material', current: '41.00', proposed: null, selectable: false, reason: 'the model has 2 materials', source_file_id: null },
    {
      field: 'dimensions',
      target: 'dimensions',
      current: { length_mm: '40.0', width_mm: '30.0', height_mm: '20.0', source: 'entered' },
      proposed: { length_mm: '42.0', width_mm: '30.0', height_mm: '20.0' },
      selectable: true,
      reason: null,
      source_file_id: 'f-stl',
    },
  ],
  notices: [],
}

function renderDialog(version = VERSION, printFileId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const onOpenChange = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <VersionActivationDialog modelId="m1" version={version} printFileId={printFileId} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return { onOpenChange }
}

describe('VersionActivationDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(getActivationPreview as Mock).mockResolvedValue(PREVIEW)
    ;(activateFileVersion as Mock).mockResolvedValue({ ...VERSION, is_active: true })
  })

  it('lists each figure old → new and names the file the dimensions come from', async () => {
    renderDialog()
    expect(await screen.findByText(/1 h 52 min →/)).toBeInTheDocument()
    expect(screen.getByText('3 h 44 min')).toBeInTheDocument()
    expect(screen.getByText('Measured from part_v2.stl')).toBeInTheDocument()
    expect(screen.getByText(/Can't apply: the model has 2 materials/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Filament weight' })).toBeDisabled()
  })

  it('shows each material line its own grams when the model has several (T067)', async () => {
    ;(getActivationPreview as Mock).mockResolvedValue({
      ...PREVIEW,
      rows: [
        {
          field: 'weight_grams',
          target: 'model_material',
          current: { 'PLA Red': '50.00', 'PLA Black': '20.00' },
          proposed: { lines: { 'mm-1': '60.00', 'mm-2': '24.00' }, labels: { 'PLA Red': '60.00', 'PLA Black': '24.00' } },
          selectable: true,
          reason: null,
          source_file_id: null,
        },
      ],
    } satisfies ActivationPreview)
    const user = userEvent.setup()
    renderDialog()
    expect(await screen.findByText(/PLA Red 50\.00 g, PLA Black 20\.00 g →/)).toBeInTheDocument()
    expect(screen.getByText('PLA Red 60.00 g, PLA Black 24.00 g')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /weight/i })).toBeChecked())
    await user.click(screen.getByRole('button', { name: 'Make active' }))
    await waitFor(() => expect(activateFileVersion).toHaveBeenCalledWith('m1', 'v2', ['weight_grams'], undefined))
  })

  it('sends only the checked figures', async () => {
    const { onOpenChange } = renderDialog()
    const user = userEvent.setup()
    await screen.findByText(/1 h 52 min →/)
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Plate print time' })).toBeChecked())
    await user.click(screen.getByRole('checkbox', { name: 'Items per plate' }))
    await user.click(screen.getByRole('checkbox', { name: 'Dimensions' }))
    await user.click(screen.getByRole('button', { name: 'Make active' }))

    await waitFor(() => expect(activateFileVersion).toHaveBeenCalledWith('m1', 'v2', ['print_time_minutes'], undefined))
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('reviews a print-file change on the active version and sends that file', async () => {
    renderDialog({ ...VERSION, is_active: true }, 'f-other')
    const user = userEvent.setup()
    expect(await screen.findByText('Change the print file of version 2')).toBeInTheDocument()
    expect(getActivationPreview).toHaveBeenCalledWith('m1', 'v2', 'f-other')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() =>
      expect(activateFileVersion).toHaveBeenCalledWith(
        'm1',
        'v2',
        ['print_time_minutes', 'prints_per_plate', 'dimensions'],
        'f-other',
      ),
    )
  })

  it('says so when no figure would change', async () => {
    ;(getActivationPreview as Mock).mockResolvedValue({ ...PREVIEW, rows: [], notices: ['The version has no measurable file, so its dimensions are not known'] })
    renderDialog()
    expect(await screen.findByText(/No figure would change/)).toBeInTheDocument()
    expect(screen.getByText(/no measurable file/)).toBeInTheDocument()
  })
})
