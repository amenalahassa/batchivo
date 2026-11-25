/**
 * The files card grouped by version (spec 004, T033; FR-007 to FR-016, FR-032).
 */
import { describe, expect, it, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, AxiosHeaders } from 'axios'

import { ModelFilesEditor } from './ModelFilesEditor'
import { listFileVersions, getActivationPreview } from '@/lib/api/modelFileVersions'
import { deleteModelFile, uploadModelFileWithResult, type ModelFile } from '@/lib/api/models'
import type { FileVersion } from '@/types/model-file-version'
import { capabilities } from '@/components/genai/genaiTestData'

const auth = vi.hoisted(() => ({ role: 'member' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'operator@example.com', role: auth.role }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})

vi.mock('@/lib/api/modelFileVersions', () => ({
  listFileVersions: vi.fn(),
  getActivationPreview: vi.fn(),
  activateFileVersion: vi.fn(),
  createFileVersion: vi.fn(),
  updateFileVersion: vi.fn(),
}))

vi.mock('@/lib/api/models', async (importOriginal) => ({
  inferModelFileType: (await importOriginal<typeof import('@/lib/api/models')>()).inferModelFileType,
  uploadModelFileWithResult: vi.fn(),
  deleteModelFile: vi.fn(),
  getModelFileDownloadUrl: vi.fn(() => '/download'),
  linkLocalModelFile: vi.fn(),
  validateLocalPath: vi.fn(),
  getModel: vi.fn(),
}))

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

// The viewer chunk is not under test here.
vi.mock('@/components/viewer/ModelViewerDialog', () => ({ default: () => null }))

const file = (over: Partial<ModelFile>): ModelFile => ({
  id: 'f',
  model_id: 'm1',
  file_type: 'source_stl',
  file_location: 'uploaded',
  original_filename: 'part.stl',
  is_primary: false,
  uploaded_at: '2026-11-01T10:00:00Z',
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-01T10:00:00Z',
  is_sliced: false,
  measurement: null,
  ...over,
})

const version = (over: Partial<FileVersion>): FileVersion => ({
  id: 'v',
  model_id: 'm1',
  sequence: 1,
  label: '1',
  note: null,
  is_active: false,
  print_file_id: null,
  created_by: { id: 'u1', name: 'Konrad' },
  created_at: '2026-11-01T10:00:00Z',
  files: [],
  has_measurable_file: false,
  open_note_count: 0,
  ...over,
})

const V1 = version({
  id: 'v1',
  sequence: 1,
  label: '1',
  is_active: true,
  print_file_id: 'g1',
  has_measurable_file: true,
  files: [
    file({ id: 's1', original_filename: 'part_v1.stl' }),
    file({ id: 'g1', original_filename: 'plate_v1.gcode.3mf', file_type: 'gcode', is_sliced: true }),
  ],
})
const V2 = version({
  id: 'v2',
  sequence: 2,
  label: '2',
  note: 'thicker walls',
  files: [file({ id: 's2', original_filename: 'part_v2.stl' })],
})

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ModelFilesEditor modelId="m1" />
    </QueryClientProvider>,
  )
}

describe('ModelFilesEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'member'
    ;(listFileVersions as Mock).mockResolvedValue([V1, V2])
    ;(getActivationPreview as Mock).mockResolvedValue({
      version_id: 'v2',
      print_file_id: null,
      dimension_file_id: 's2',
      dimension_file_name: 'part_v2.stl',
      rows: [],
      notices: [],
    })
  })

  it('lists versions newest first with their note, author and active badge', async () => {
    renderEditor()
    const list = await screen.findByRole('list', { name: 'Versions' })
    const items = within(list).getAllByRole('listitem', { name: /^Version / })
    expect(items.map((i) => i.getAttribute('aria-label'))).toEqual(['Version 2', 'Version 1'])
    expect(within(items[0]).getByText('thicker walls')).toBeInTheDocument()
    expect(within(items[1]).getByText('Active')).toBeInTheDocument()
    expect(within(items[1]).getByText('Print file')).toBeInTheDocument()
    expect(within(items[0]).getAllByText(/Konrad/).length).toBeGreaterThan(0)
  })

  it('offers "Make active" for an inactive version and opens the review', async () => {
    renderEditor()
    const user = userEvent.setup()
    const v2 = await screen.findByRole('listitem', { name: 'Version 2' })
    await user.click(within(v2).getByRole('button', { name: 'Make active' }))
    expect(await screen.findByText('Make version 2 active')).toBeInTheDocument()
    expect(getActivationPreview).toHaveBeenCalledWith('m1', 'v2', undefined)
  })

  it('offers to make a version active right after an upload created it', async () => {
    ;(uploadModelFileWithResult as Mock).mockResolvedValue({
      file: file({ id: 's3', version_id: 'v2' }),
      version_created: true,
    })
    renderEditor()
    const user = userEvent.setup()
    await screen.findByRole('list', { name: 'Versions' })
    await user.upload(screen.getByLabelText('Choose files to upload'), new File([new Uint8Array([1])], 'part_v3.stl'))
    expect(await screen.findByText(/Version 2 was created/)).toBeInTheDocument()
  })

  it('says why a delete was refused, in plain words', async () => {
    ;(deleteModelFile as Mock).mockRejectedValue(
      new AxiosError('Conflict', '409', undefined, undefined, {
        status: 409,
        statusText: 'Conflict',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: { code: 'active_print_file', message: 'raw' } },
      }),
    )
    renderEditor()
    const user = userEvent.setup()
    const v1 = await screen.findByRole('listitem', { name: 'Version 1' })
    const printRow = within(v1).getByText('plate_v1.gcode.3mf').closest('li') as HTMLElement
    await user.click(within(printRow).getByTitle('Delete'))
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "This is the active version's print file. Choose another print file",
    )
  })

  it('says when the active version has no measurable file', async () => {
    ;(listFileVersions as Mock).mockResolvedValue([{ ...V1, has_measurable_file: false }])
    renderEditor()
    expect(await screen.findByText(/No measurable file in the active version/)).toBeInTheDocument()
  })

  it('shows a viewer no write action', async () => {
    auth.role = 'viewer'
    renderEditor()
    await screen.findByRole('list', { name: 'Versions' })
    expect(screen.queryByText('Upload File')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Make active' })).not.toBeInTheDocument()
    expect(screen.queryByTitle('Delete')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Use as print file')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit version/ })).not.toBeInTheDocument()
    // Reading stays open: view and download.
    expect(screen.getAllByTitle('View').length).toBe(3)
    expect(screen.getAllByTitle('Download').length).toBe(3)
  })

  it('reviews the change before switching the active version to another print file', async () => {
    const extra = file({ id: 'g2', original_filename: 'plate_v1b.gcode', file_type: 'gcode', is_sliced: true })
    ;(listFileVersions as Mock).mockResolvedValue([{ ...V1, files: [...V1.files, extra] }])
    renderEditor()
    const user = userEvent.setup()
    const row = (await screen.findByText('plate_v1b.gcode')).closest('li') as HTMLElement
    await user.click(within(row).getByTitle('Use as print file'))
    await waitFor(() => expect(getActivationPreview).toHaveBeenCalledWith('m1', 'v1', 'g2'))
  })
})

// ============================================
// Generative AI (spec 008, US4)
// ============================================

describe('ModelFilesEditor generative AI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'member'
    ;(listFileVersions as Mock).mockResolvedValue([V1, V2])
    genai.getBlob.mockImplementation(() => new Promise(() => {}))
    genai.capabilities.mockResolvedValue({ connected: false, token_source: 'none', currency: 'USD', capabilities: [] })
  })

  it('offers "Draft 3D from image" to a member and opens the dialog', async () => {
    const user = userEvent.setup()
    renderEditor()
    await screen.findByRole('list', { name: 'Versions' })
    await user.click(screen.getByRole('button', { name: 'Draft 3D from image' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: /Draft 3D from image/ })).toBeInTheDocument()
  })

  it('hides "Draft 3D from image" from a viewer', async () => {
    auth.role = 'viewer'
    renderEditor()
    await screen.findByRole('list', { name: 'Versions' })
    expect(screen.queryByRole('button', { name: 'Draft 3D from image' })).not.toBeInTheDocument()
  })

  it('marks a version labelled "AI draft" with the AI badge', async () => {
    ;(listFileVersions as Mock).mockResolvedValue([
      V1,
      version({ id: 'v3', sequence: 3, label: 'AI draft', files: [file({ id: 's3', original_filename: 'ai-draft.stl' })] }),
    ])
    renderEditor()
    const draft = await screen.findByRole('listitem', { name: 'Version AI draft' })
    expect(within(draft).getByLabelText('AI draft: made with generative AI')).toBeInTheDocument()
    const v1 = screen.getByRole('listitem', { name: 'Version 1' })
    expect(within(v1).queryByLabelText(/made with generative AI/)).not.toBeInTheDocument()
  })

  it('lists the model generations in a collapsible section', async () => {
    genai.listJobs.mockResolvedValue({ items: [], total: 0 })
    const user = userEvent.setup()
    renderEditor()
    await screen.findByRole('list', { name: 'Versions' })
    await user.click(screen.getByRole('button', { name: /AI generations/ }))
    expect(await screen.findByText('No AI generations yet.')).toBeInTheDocument()
  })
})

// ============================================
// The model's own image as the 3D input (spec 008 US4 AS1, FR-032, T109)
// ============================================

describe('ModelFilesEditor AI input', () => {
  const withDraft3d = () => {
    const response = capabilities()
    response.capabilities.push({
      ...response.capabilities[1],
      capability: 'image_to_3d',
      label: 'Draft 3D from image',
      output_kind: 'mesh',
      shows_real_item: false,
    })
    return response
  }

  function renderWithModel(imageUrl: string | null) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    client.setQueryData(['model', 'm1'], { id: 'm1', name: 'Visor clip', image_url: imageUrl })
    return render(
      <QueryClientProvider client={client}>
        <ModelFilesEditor modelId="m1" />
      </QueryClientProvider>,
    )
  }

  function refused(status: number, code: string, message: string) {
    const headers = new AxiosHeaders()
    return new AxiosError('refused', String(status), undefined, undefined, {
      status,
      statusText: '',
      headers,
      config: { headers },
      data: { detail: { code, message } },
    })
  }

  beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'member'
    ;(listFileVersions as Mock).mockResolvedValue([V1, V2])
    genai.getBlob.mockImplementation(() => new Promise(() => {}))
    genai.capabilities.mockResolvedValue(withDraft3d())
    genai.estimate.mockResolvedValue({
      estimated_cost: '0.0100',
      month_to_date: '0.0000',
      budget: null,
      would_exceed_budget: false,
      currency: 'USD',
    })
  })

  async function openDraft() {
    const user = userEvent.setup()
    await screen.findByRole('list', { name: 'Versions' })
    await user.click(screen.getByRole('button', { name: 'Draft 3D from image' }))
    return { user, dialog: await screen.findByRole('dialog') }
  }

  it("offers the model's image and sends it as a model_image input", async () => {
    genai.createJob.mockRejectedValue(
      refused(422, 'input_invalid', "This model's image is not stored in Batchivo; upload it instead")
    )
    renderWithModel('/uploads/products/m1/a.png')
    const { user, dialog } = await openDraft()
    const image = await within(dialog).findByRole('button', { name: 'Visor clip image' })
    if (image.getAttribute('aria-pressed') !== 'true') await user.click(image)
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }))
    await waitFor(() => expect(genai.createJob).toHaveBeenCalled())
    expect(genai.createJob.mock.calls[0][0].inputs.input_assets).toEqual([
      { type: 'model_image', id: 'm1' },
    ])
    expect(
      await within(dialog).findByText(/This model's image is not stored in Batchivo/)
    ).toBeInTheDocument()
  })

  it('offers no model image when the model has none', async () => {
    renderWithModel(null)
    const { dialog } = await openDraft()
    await within(dialog).findByRole('heading', { name: /Draft 3D from image/ })
    expect(within(dialog).queryByRole('button', { name: 'Visor clip image' })).not.toBeInTheDocument()
  })
})
