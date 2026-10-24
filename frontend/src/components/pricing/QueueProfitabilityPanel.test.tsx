/**
 * The queue ranked by profit per machine-hour is on screen (T234, FR-043).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { QueueProfitabilityPanel } from './QueueProfitabilityPanel'
import { printQueueApi } from '@/lib/api/printQueue'
import type { JobProfitability } from '@/types/pricing'

vi.mock('@/lib/api/printQueue', () => ({
  printQueueApi: { profitability: vi.fn() },
}))

const api = vi.mocked(printQueueApi)

function entry(overrides: Partial<JobProfitability> = {}): JobProfitability {
  return {
    job_id: 'job-1',
    status: 'pending',
    priority: 'normal',
    queue_position: 1,
    model_name: 'quick part',
    product_name: 'Quick product',
    profit_per_machine_hour: '9.17',
    margin_pct: '35.30',
    machine_hours: '2.5000',
    reason: null,
    ...overrides,
  }
}

function renderPanel(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('QueueProfitabilityPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.profitability.mockResolvedValue({ as_of: '2026-10-24', entries: [] })
  })

  it('lists the jobs in the order the ranking gives, with the figure beside the margin', async () => {
    api.profitability.mockResolvedValue({
      as_of: '2026-10-24',
      entries: [
        entry(),
        entry({
          job_id: 'job-2',
          product_name: 'Slow product',
          profit_per_machine_hour: '2.29',
          machine_hours: '10.0000',
        }),
      ],
    })
    renderPanel(<QueueProfitabilityPanel />)

    const quick = within(await screen.findByTestId('queue-job-job-1'))
    expect(quick.getByText('Quick product')).toBeInTheDocument()
    expect(quick.getByText('£9.17')).toBeInTheDocument()
    expect(quick.getByText('35.3%')).toBeInTheDocument()

    const rows = screen.getAllByTestId(/^queue-job-job-/)
    expect(rows.map((row) => row.dataset.testid)).toEqual(['queue-job-job-1', 'queue-job-job-2'])
  })

  it('shows a job with no figure as a dash with its reason, never zero', async () => {
    api.profitability.mockResolvedValue({
      as_of: '2026-10-24',
      entries: [
        entry({
          profit_per_machine_hour: null,
          margin_pct: null,
          machine_hours: null,
          reason: 'nobody has timed this print',
        }),
      ],
    })
    renderPanel(<QueueProfitabilityPanel />)

    const row = within(await screen.findByTestId('queue-job-job-1'))
    expect(row.getByTestId('queue-job-reason')).toHaveTextContent('nobody has timed this print')
    expect(row.queryByText('£0.00')).not.toBeInTheDocument()
  })

  it('asks for the jobs in the status chosen', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<QueueProfitabilityPanel />)

    expect(await screen.findByTestId('queue-profitability-empty')).toBeInTheDocument()
    expect(api.profitability).toHaveBeenCalledWith({ status: 'pending' })

    await user.selectOptions(screen.getByLabelText('Jobs'), 'queued')
    await waitFor(() => expect(api.profitability).toHaveBeenCalledWith({ status: 'queued' }))
  })
})
