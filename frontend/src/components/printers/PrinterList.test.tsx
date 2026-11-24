/**
 * PrinterList row actions for print send (spec 011, FR-014):
 * "Send print" is shown only when the printer's connection allows it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { PrinterList } from './PrinterList'
import { getPrinterConnection, listPrinters } from '@/lib/api/printers'
import type { Printer, PrinterConnection } from '@/types/printer'

vi.mock('@/lib/api/printers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/printers')>()
  return { ...actual, listPrinters: vi.fn(), getPrinterConnection: vi.fn() }
})
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: null }) }))

const printer = {
  id: 'printer-1',
  tenant_id: 'tenant-1',
  name: 'X1 Carbon',
  is_active: true,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
} as unknown as Printer

function connection(overrides: Partial<PrinterConnection>): PrinterConnection {
  return {
    id: 'conn-1',
    printer_id: 'printer-1',
    connection_type: 'bambu_lan',
    port: 8883,
    ams_count: 1,
    is_enabled: true,
    developer_mode: false,
    can_send_prints: false,
    is_connected: false,
    ...overrides,
  }
}

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PrinterList />
    </QueryClientProvider>
  )
}

describe('PrinterList print send actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listPrinters).mockResolvedValue({ printers: [printer], total: 1, skip: 0, limit: 100 })
  })

  it('hides Send print when Developer Mode is off', async () => {
    vi.mocked(getPrinterConnection).mockResolvedValue(connection({}))
    renderList()

    expect((await screen.findAllByLabelText('Connection for X1 Carbon')).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Send print to X1 Carbon')).not.toBeInTheDocument()
  })

  it('shows Send print when the connection can send', async () => {
    vi.mocked(getPrinterConnection).mockResolvedValue(
      connection({ developer_mode: true, can_send_prints: true })
    )
    renderList()

    expect((await screen.findAllByLabelText('Send print to X1 Carbon')).length).toBeGreaterThan(0)
  })

  it('offers only the connection for a printer without one', async () => {
    vi.mocked(getPrinterConnection).mockResolvedValue(null)
    renderList()

    expect((await screen.findAllByLabelText('Connection for X1 Carbon')).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Sends of X1 Carbon')).not.toBeInTheDocument()
  })
})
