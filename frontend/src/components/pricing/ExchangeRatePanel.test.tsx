/**
 * An exchange rate can be entered by hand for the sales waiting on one (T223).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, AxiosHeaders } from 'axios'
import type { ReactNode } from 'react'

import { ExchangeRatePanel } from './ExchangeRatePanel'
import { fxRatesApi } from '@/lib/api/fxRates'
import type { FxWaitingLine } from '@/types/pricing'

vi.mock('@/lib/api/fxRates', () => ({
  fxRatesApi: { waiting: vi.fn(), recordManual: vi.fn() },
}))

const api = vi.mocked(fxRatesApi)

function line(overrides: Partial<FxWaitingLine> = {}): FxWaitingLine {
  return {
    order_id: 'order-1',
    order_number: 'ORD-0001',
    order_item_id: 'item-1',
    product_name: 'Dragon',
    sold_on: '2026-10-01',
    base_currency: 'USD',
    quote_currency: 'GBP',
    ...overrides,
  }
}

function renderPanel(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('ExchangeRatePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.waiting.mockResolvedValue({ lines: [], total: 0 })
  })

  it('says when no sale is waiting on a rate', async () => {
    renderPanel(<ExchangeRatePanel />)
    expect(await screen.findByTestId('fx-nothing-waiting')).toBeInTheDocument()
  })

  it('groups the waiting lines by the pair one rate would answer', async () => {
    api.waiting.mockResolvedValue({
      lines: [
        line(),
        line({ order_item_id: 'item-2', order_number: 'ORD-0002' }),
        line({ order_item_id: 'item-3', base_currency: 'EUR' }),
      ],
      total: 3,
    })
    renderPanel(<ExchangeRatePanel />)

    expect(await screen.findByTestId('fx-waiting-USD/GBP')).toHaveTextContent('2 waiting')
    expect(screen.getByTestId('fx-waiting-EUR/GBP')).toHaveTextContent('1 waiting')
  })

  it('sends the rate as the decimal string it was typed as', async () => {
    api.waiting.mockResolvedValue({ lines: [line()], total: 1 })
    api.recordManual.mockResolvedValue({
      base_currency: 'USD',
      quote_currency: 'GBP',
      rate: '0.78500',
      rate_date: '2026-10-01',
      source: 'manual',
      lines_filled: 1,
    })
    const user = userEvent.setup({ delay: null })
    renderPanel(<ExchangeRatePanel />)

    // Choosing the waiting pair fills the currencies and the day it was sold.
    await user.click(await screen.findByRole('button', { name: /enter this rate/i }))
    await user.type(screen.getByLabelText('Rate'), '0.78500')
    await user.click(screen.getByRole('button', { name: /record rate/i }))

    await waitFor(() => expect(api.recordManual).toHaveBeenCalled())
    const sent = api.recordManual.mock.calls[0][0]
    expect(sent).toEqual({
      base_currency: 'USD',
      quote_currency: 'GBP',
      rate: '0.78500',
      rate_date: '2026-10-01',
    })
    expect(typeof sent.rate).toBe('string')
    expect(await screen.findByTestId('fx-recorded')).toHaveTextContent('1 waiting line filled')
  })

  it('refuses parity and a rate that is not a positive decimal before sending', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<ExchangeRatePanel />)

    await user.type(await screen.findByLabelText('From'), 'GBP')
    await user.type(screen.getByLabelText('To'), 'gbp')
    await user.type(screen.getByLabelText('Rate'), '1')
    await user.click(screen.getByRole('button', { name: /record rate/i }))
    expect(screen.getByTestId('fx-invalid')).toHaveTextContent(/parity/)

    await user.clear(screen.getByLabelText('To'))
    await user.type(screen.getByLabelText('To'), 'USD')
    await user.clear(screen.getByLabelText('Rate'))
    await user.type(screen.getByLabelText('Rate'), '0')
    await user.click(screen.getByRole('button', { name: /record rate/i }))
    expect(screen.getByTestId('fx-invalid')).toHaveTextContent(/positive decimal/)
    expect(api.recordManual).not.toHaveBeenCalled()
  })

  it('shows why a second rate for the same day was refused', async () => {
    api.recordManual.mockRejectedValue(
      new AxiosError('Request failed with status code 409', '409', undefined, undefined, {
        status: 409,
        statusText: 'Conflict',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: 'a manual rate of 0.78 is already recorded for USD/GBP on 2026-10-01' },
      }),
    )
    const user = userEvent.setup({ delay: null })
    renderPanel(<ExchangeRatePanel />)

    await user.type(await screen.findByLabelText('From'), 'USD')
    await user.type(screen.getByLabelText('To'), 'GBP')
    await user.type(screen.getByLabelText('Rate'), '0.79')
    await user.click(screen.getByRole('button', { name: /record rate/i }))

    expect(await screen.findByTestId('fx-refused')).toHaveTextContent(/already recorded/)
  })

  it('shows a viewer the waiting list with the form disabled', async () => {
    api.waiting.mockResolvedValue({ lines: [line()], total: 1 })
    renderPanel(<ExchangeRatePanel canEdit={false} />)

    expect(await screen.findByTestId('fx-waiting-USD/GBP')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /enter this rate/i })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Rate')).toBeDisabled()
    expect(screen.getByTestId('fx-read-only')).toBeInTheDocument()
  })
})
