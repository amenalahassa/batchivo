/**
 * PrinterConnectionDialog (spec 011, US3): Developer Mode, its explanation, and the transfer test.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { PrinterConnectionDialog } from './PrinterConnectionDialog'
import {
  getPrinterConnection,
  savePrinterConnection,
  testFileTransfer,
} from '@/lib/api/printers'
import type { PrinterConnection } from '@/types/printer'

vi.mock('@/lib/api/printers', () => ({
  getPrinterConnection: vi.fn(),
  savePrinterConnection: vi.fn(),
  testFileTransfer: vi.fn(),
}))

function connection(overrides: Partial<PrinterConnection> = {}): PrinterConnection {
  return {
    id: 'conn-1',
    printer_id: 'printer-1',
    connection_type: 'bambu_lan',
    serial_number: '01S00C123456789',
    ip_address: '192.168.1.50',
    port: 8883,
    access_code: '****4321',
    ams_count: 1,
    is_enabled: true,
    developer_mode: false,
    can_send_prints: false,
    is_connected: false,
    connection_error: null,
    ...overrides,
  }
}

function renderDialog(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

const open = () =>
  renderDialog(
    <PrinterConnectionDialog
      open
      onOpenChange={() => {}}
      printerId="printer-1"
      printerName="X1 Carbon"
    />
  )

describe('PrinterConnectionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getPrinterConnection).mockResolvedValue(connection())
  })

  it('explains what Developer Mode enables and disables', async () => {
    open()
    expect(await screen.findByLabelText('Developer Mode is on on this printer')).toBeInTheDocument()
    expect(screen.getByText(/turns off Bambu cloud access/)).toBeInTheDocument()
    expect(screen.getByText(/Bambu Studio or Bambu Connect/)).toBeInTheDocument()
  })

  it('saves Developer Mode without resending the stored access code', async () => {
    vi.mocked(savePrinterConnection).mockResolvedValue(
      connection({ developer_mode: true, can_send_prints: true })
    )
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByLabelText('Developer Mode is on on this printer'))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(savePrinterConnection).toHaveBeenCalledWith('printer-1', {
        connection_type: 'bambu_lan',
        serial_number: '01S00C123456789',
        ip_address: '192.168.1.50',
        access_code: undefined,
        developer_mode: true,
      })
    )
    expect(await screen.findByText('Connection saved.')).toBeInTheDocument()
  })

  it('shows a failed transfer test without blocking the save', async () => {
    vi.mocked(testFileTransfer).mockResolvedValue({
      ok: false,
      message: 'Login refused: check the access code',
    })
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Test file transfer' }))

    expect(await screen.findByText('Login refused: check the access code')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('leaves a non-Bambu connection alone', async () => {
    vi.mocked(getPrinterConnection).mockResolvedValue(connection({ connection_type: 'moonraker' }))
    open()
    expect(await screen.findByText(/uses a moonraker connection/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})
