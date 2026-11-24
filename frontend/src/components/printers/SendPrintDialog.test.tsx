/**
 * SendPrintDialog (spec 011, US1–US2): prepare, then confirm only on an
 * explicit acknowledgement of the summary's warnings.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, AxiosHeaders } from 'axios'
import type { ReactNode } from 'react'

import { SendPrintDialog } from './SendPrintDialog'
import { printSendsApi } from '@/lib/api/printSends'
import { listModels, parse3mfFile } from '@/lib/api/models'
import type { PrintSend, PrintSendPrepared } from '@/types/printSend'
import { summaryFixture } from './printSendFixtures'

vi.mock('@/lib/api/printSends', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/printSends')>()
  return {
    ...actual,
    printSendsApi: { prepare: vi.fn(), confirm: vi.fn(), list: vi.fn() },
  }
})
vi.mock('@/lib/api/models', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/models')>()
  return {
    ...actual,
    listModels: vi.fn(),
    getModelFiles: vi.fn(),
    parse3mfFile: vi.fn(),
  }
})

const api = vi.mocked(printSendsApi)

function prepared(overrides: Partial<PrintSendPrepared> = {}): PrintSendPrepared {
  return { ...summaryFixture(), confirmation_token: 'token-abc', ...overrides }
}

function renderDialog(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

async function prepareWithUpload() {
  const user = userEvent.setup()
  renderDialog(
    <SendPrintDialog open onOpenChange={() => {}} printerId="printer-1" printerName="X1 Carbon" />
  )
  const file = new File(['zip'], 'dragon.gcode.3mf')
  await user.upload(screen.getByLabelText('Sliced file (.gcode.3mf)'), file)
  await screen.findByLabelText('Plate')
  await user.click(screen.getByRole('button', { name: 'Prepare' }))
  return { user, file }
}

function apiError(status: number, code: string, message: string) {
  return new AxiosError('failed', String(status), undefined, undefined, {
    status,
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: { detail: { code, message } },
  })
}

describe('SendPrintDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listModels).mockResolvedValue({ models: [], total: 0, skip: 0, limit: 100 })
    vi.mocked(parse3mfFile).mockResolvedValue({
      print_time_minutes: 95,
      filament_weight_grams: 35.1,
      plate_count: 2,
      source_plate_index: 1,
      slicer_detected: 'bambu_orca',
      thumbnail_available: false,
      plates: [
        {
          index: 1,
          print_time_minutes: 95,
          filament_weight_grams: 35.1,
          filaments: [
            { id: 1, type: 'PLA', color: '#FF0000', grams: 30.1 },
            { id: 3, type: 'PETG', color: '#00FF00', grams: 5 },
          ],
        },
      ],
    })
  })

  it('prepares with the plate and one slot per filament', async () => {
    api.prepare.mockResolvedValue(prepared())
    const { file } = await prepareWithUpload()

    await screen.findByTestId('print-send-summary')
    expect(api.prepare).toHaveBeenCalledWith('printer-1', {
      plate: 1,
      mapping: [
        { filament_id: 1, slot: { kind: 'ams', ams_id: 0, tray_id: 0 } },
        { filament_id: 3, slot: { kind: 'ams', ams_id: 0, tray_id: 2 } },
      ],
      file,
      modelFileId: undefined,
      attachToModelId: undefined,
    })
    expect(api.confirm).not.toHaveBeenCalled()
  })

  it('needs the acknowledgement before Start print', async () => {
    api.prepare.mockResolvedValue(prepared())
    api.confirm.mockResolvedValue({ ...prepared(), status: 'started' } as unknown as PrintSend)
    const { user } = await prepareWithUpload()

    const start = await screen.findByRole('button', { name: 'Start print' })
    expect(start).toBeDisabled()

    await user.click(screen.getByLabelText('I have checked the warnings'))
    expect(start).toBeEnabled()
    await user.click(start)

    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith('printer-1', 'token-abc', true))
    expect(await screen.findByText('Print started')).toBeInTheDocument()
  })

  it('needs no acknowledgement for a summary without warnings', async () => {
    api.prepare.mockResolvedValue(
      prepared({ warnings: [], requires_acknowledgement: false })
    )
    await prepareWithUpload()

    expect(screen.queryByLabelText('I have checked the warnings')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Start print' })).toBeEnabled()
  })

  it('disables Start print while the printer is busy', async () => {
    api.prepare.mockResolvedValue(
      prepared({
        requires_acknowledgement: false,
        blockers: [{ code: 'printer_busy', message: 'The printer is busy (RUNNING)', filament_id: null }],
      })
    )
    await prepareWithUpload()
    expect(await screen.findByRole('button', { name: 'Start print' })).toBeDisabled()
  })

  it('explains an expired confirmation', async () => {
    api.prepare.mockResolvedValue(prepared({ requires_acknowledgement: false, warnings: [] }))
    api.confirm.mockRejectedValue(apiError(410, 'send_expired', 'window passed'))
    const { user } = await prepareWithUpload()

    await user.click(await screen.findByRole('button', { name: 'Start print' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Prepare the send again')
  })

  it('shows the server message when prepare is refused', async () => {
    api.prepare.mockRejectedValue(
      apiError(422, 'plate_not_found', 'Plate 3 is not in the file; available plates: 1, 2')
    )
    await prepareWithUpload()
    expect(await screen.findByRole('alert')).toHaveTextContent('available plates: 1, 2')
  })
})
