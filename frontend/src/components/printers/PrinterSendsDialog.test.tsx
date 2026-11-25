/**
 * PrinterSendsDialog (spec 011, US4): recent sends and the spool deduction proposal.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { PrinterSendsDialog } from './PrinterSendsDialog'
import { printSendsApi } from '@/lib/api/printSends'
import { spoolsApi } from '@/lib/api/spools'
import type { PrintSend } from '@/types/printSend'
import { summaryFixture } from './printSendFixtures'

vi.mock('@/lib/api/printSends', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/printSends')>()
  return {
    ...actual,
    printSendsApi: {
      list: vi.fn(),
      acceptConsumption: vi.fn(),
      dismissConsumption: vi.fn(),
    },
  }
})

vi.mock('@/lib/api/spools', () => ({
  spoolsApi: {
    list: vi.fn().mockResolvedValue({
      total: 2,
      page: 1,
      page_size: 100,
      spools: [
        {
          id: 'spool-1',
          spool_id: 'SP-PLA',
          filament_type: { material_type_code: 'PLA', color: 'Red' },
        },
        {
          id: 'spool-9',
          spool_id: 'SP-EXT',
          filament_type: { material_type_code: 'PETG', color: 'Green' },
        },
      ],
    }),
  },
}))

const api = vi.mocked(printSendsApi)

function send(overrides: Partial<PrintSend> = {}): PrintSend {
  return {
    ...summaryFixture(),
    status: 'started',
    created_at: '2026-11-23T10:00:00Z',
    confirmed_at: '2026-11-23T10:01:00Z',
    warnings_acknowledged: true,
    error_message: null,
    print_job: {
      id: 'job-1',
      status: 'completed',
      started_at: '2026-11-23T10:01:00Z',
      completed_at: '2026-11-23T11:40:00Z',
    },
    consumption: {
      status: 'pending',
      lines: [
        {
          filament_id: 1,
          spool_id: 'spool-1',
          proposed_grams: '30.10',
          accepted_grams: null,
          transaction_id: null,
        },
        {
          filament_id: 3,
          spool_id: null,
          proposed_grams: '5.00',
          accepted_grams: null,
          transaction_id: null,
        },
      ],
      decided_at: null,
    },
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

const open = () =>
  renderDialog(
    <PrinterSendsDialog
      open
      onOpenChange={() => {}}
      printerId="printer-1"
      printerName="X1 Carbon"
    />
  )

describe('PrinterSendsDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('accepts a corrected amount and leaves lines without spool out', async () => {
    api.list.mockResolvedValue([send()])
    api.acceptConsumption.mockResolvedValue(
      send({ consumption: { ...send().consumption, status: 'accepted' } })
    )
    const user = userEvent.setup()
    open()

    const grams = await screen.findByLabelText('Grams for filament 1')
    expect(screen.getByLabelText('Grams for filament 3')).toBeDisabled()
    await user.clear(grams)
    await user.type(grams, '12.5')
    await user.click(screen.getByRole('button', { name: 'Accept deduction' }))

    await waitFor(() =>
      expect(api.acceptConsumption).toHaveBeenCalledWith('printer-1', 'send-1', [
        { filament_id: 1, spool_id: 'spool-1', grams: '12.5' },
      ])
    )
  })

  it('lets the operator pick a spool for a line with none recorded', async () => {
    api.list.mockResolvedValue([send()])
    api.acceptConsumption.mockResolvedValue(send())
    const user = userEvent.setup()
    open()

    const picker = await screen.findByLabelText('Spool for filament 3')
    await screen.findAllByRole('option', { name: /SP-EXT/ })
    await user.selectOptions(picker, 'spool-9')
    expect(screen.getByLabelText('Grams for filament 3')).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Accept deduction' }))

    await waitFor(() =>
      expect(api.acceptConsumption).toHaveBeenCalledWith('printer-1', 'send-1', [
        { filament_id: 1, spool_id: 'spool-1', grams: '30.10' },
        { filament_id: 3, spool_id: 'spool-9', grams: '5.00' },
      ])
    )
  })

  it('offers spools beyond the first page', async () => {
    const page = (n: number, count: number) =>
      Array.from({ length: count }, (_, i) => ({
        id: `spool-p${n}-${i}`,
        spool_id: `SP-${n}-${i}`,
        filament_type: { material_type_code: 'PLA', color: 'Red' },
      }))
    vi.mocked(spoolsApi.list)
      .mockResolvedValueOnce({ total: 101, page: 1, page_size: 100, spools: page(1, 100) } as never)
      .mockResolvedValueOnce({ total: 101, page: 2, page_size: 100, spools: page(2, 1) } as never)
    api.list.mockResolvedValue([send()])
    open()

    expect(await screen.findAllByRole('option', { name: /SP-2-0/ })).not.toHaveLength(0)
    expect(spoolsApi.list).toHaveBeenCalledWith({ is_active: true, page: 2, page_size: 100 })
  })

  it('shows who confirmed and the confirmed slot mapping', async () => {
    api.list.mockResolvedValue([send({ confirmed_by: { id: 'user-1', name: 'Alex Operator' } })])
    open()

    expect(await screen.findByText(/by Alex Operator/)).toBeInTheDocument()
    const mapping = screen.getByRole('list', {
      name: 'Slot mapping of dragon.gcode.3mf',
    })
    expect(mapping).toHaveTextContent('Filament 1 (PLA) → AMS 1 · slot 2 · SP-PETG')
    expect(mapping).toHaveTextContent('Filament 3 (PETG) → External spool')
  })

  it('dismisses the proposal', async () => {
    api.list.mockResolvedValue([send()])
    api.dismissConsumption.mockResolvedValue(send())
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(api.dismissConsumption).toHaveBeenCalledWith('printer-1', 'send-1'))
  })

  it('shows the job status and hides unconfirmed summaries', async () => {
    api.list.mockResolvedValue([
      send({ consumption: { status: 'none', lines: [], decided_at: null } }),
      send({ id: 'send-2', status: 'prepared', print_job: null }),
    ])
    open()

    expect(await screen.findByText('Job completed')).toBeInTheDocument()
    expect(screen.getAllByText(/dragon.gcode.3mf/)).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Accept deduction' })).not.toBeInTheDocument()
  })
})
