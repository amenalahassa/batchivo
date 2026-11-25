/** Recording a test print (spec 009, US4, clarification Q3). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'
import { printTestResultsApi } from '@/lib/api/preflight'
import { RecordTestResultDialog } from './RecordTestResultDialog'
import { measurementsOf } from './preflightLogic'
import { aTestResult } from './preflightTestData'

vi.mock('@/lib/api/preflight', () => ({
  printTestResultsApi: { create: vi.fn(), uploadPhoto: vi.fn(), list: vi.fn(), update: vi.fn() },
}))
vi.mock('@/lib/api/spools', () => ({
  materialTypesApi: { list: vi.fn().mockResolvedValue([{ id: 'pla', code: 'PLA', name: 'PLA' }]) },
}))
vi.mock('@/lib/api/modelFileVersions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/modelFileVersions')>()),
  listFileVersions: vi.fn().mockResolvedValue([
    { id: 'v1', label: '1', is_active: false, files: [] },
    { id: 'v2', label: '2', is_active: true, files: [] },
  ]),
}))

describe('measurementsOf', () => {
  it('keeps the filled rows, values as typed', () => {
    expect(
      measurementsOf([
        { name: 'gap', value: '0.15', unit: 'mm' },
        { name: '', value: '', unit: '' },
        { name: 'load', value: '7', unit: '' },
      ])
    ).toEqual([
      { name: 'gap', value: '0.15', unit: 'mm' },
      { name: 'load', value: '7' },
    ])
  })
})

describe('RecordTestResultDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(printTestResultsApi.create).mockResolvedValue(aTestResult({ id: 'r1' }))
  })

  it('records against the active version by default', async () => {
    const onOpenChange = vi.fn()
    render(<RecordTestResultDialog modelId="model-1" open onOpenChange={onOpenChange} />)
    await screen.findByRole('option', { name: '2 (active)' })
    await userEvent.selectOptions(screen.getByLabelText('Outcome'), 'fail')
    await userEvent.type(screen.getByLabelText('Measurement 1 name'), 'load_kg')
    await userEvent.type(screen.getByLabelText('Measurement 1 value'), '7')
    await userEvent.type(screen.getByLabelText('Failure mode'), 'broke at 7 kg')
    await userEvent.click(screen.getByRole('button', { name: 'Record result' }))
    await waitFor(() =>
      expect(printTestResultsApi.create).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: 'critical_zone',
          outcome: 'fail',
          model_id: 'model-1',
          model_file_version_id: 'v2',
          measurements: [{ name: 'load_kg', value: '7' }],
          failure_mode: 'broke at 7 kg',
        })
      )
    )
    expect(printTestResultsApi.uploadPhoto).not.toHaveBeenCalled()
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('uploads the photo after recording', async () => {
    vi.mocked(printTestResultsApi.uploadPhoto).mockResolvedValue(aTestResult({ id: 'r1', photo_available: true }))
    render(<RecordTestResultDialog modelId="model-1" open onOpenChange={vi.fn()} />)
    await screen.findByRole('option', { name: '2 (active)' })
    const photo = new File(['x'], 'break.jpg', { type: 'image/jpeg' })
    await userEvent.upload(screen.getByLabelText('Photo'), photo)
    await userEvent.click(screen.getByRole('button', { name: 'Record result' }))
    await waitFor(() => expect(printTestResultsApi.uploadPhoto).toHaveBeenCalledWith('r1', photo))
  })
})
