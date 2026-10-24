/**
 * FeeActualForm tests (T224).
 *
 * What matters: both scopes reach the API with the amount as a decimal string,
 * an order scope can name its statement period, a 409 shows the server's
 * reason, and a member meets a disabled form rather than a missing one.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'
import { FeeActualForm } from './FeeActualForm'

const recordFeeActual = vi.fn()

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: { recordFeeActual: (...args: unknown[]) => recordFeeActual(...args) },
}))

const PROPS = { channelId: 'channel-1', periodStart: '2026-03-01', periodEnd: '2026-03-31' }

function conflict(message: string) {
  const headers = new AxiosHeaders()
  return new AxiosError('Request failed with status code 409', '409', undefined, undefined, {
    status: 409,
    statusText: 'Conflict',
    headers,
    config: { headers },
    data: { detail: message },
  })
}

describe('FeeActualForm', () => {
  beforeEach(() => {
    recordFeeActual.mockReset()
    recordFeeActual.mockResolvedValue({
      id: 'actual-1',
      fee_category: 'transaction',
      amount: '12.40',
      source: 'entered',
    })
  })

  it('records a period total, sending the amount as typed', async () => {
    const user = userEvent.setup({ delay: null })
    render(<FeeActualForm {...PROPS} />)

    await user.type(screen.getByLabelText('Fee category'), 'transaction')
    await user.type(screen.getByLabelText(/Amount/), '12.40')
    await user.click(screen.getByRole('button', { name: 'Record fee' }))

    await waitFor(() => expect(recordFeeActual).toHaveBeenCalled())
    expect(recordFeeActual.mock.calls[0][0]).toEqual({
      sales_channel_id: 'channel-1',
      fee_category: 'transaction',
      amount: '12.40',
      period_start: '2026-03-01',
      period_end: '2026-03-31',
    })
    expect(await screen.findByTestId('fee-actual-recorded')).toHaveTextContent('as entered')
  })

  it('records one order with its statement period', async () => {
    const user = userEvent.setup({ delay: null })
    render(<FeeActualForm {...PROPS} />)

    await user.click(screen.getByLabelText('One order'))
    await user.type(screen.getByLabelText('Fee category'), 'transaction')
    await user.type(screen.getByLabelText(/Amount/), '3.10')
    await user.type(screen.getByLabelText('Order ID'), 'order-7')
    await user.type(screen.getByLabelText('Statement period start'), '2026-02-01')
    await user.type(screen.getByLabelText('Statement period end'), '2026-02-28')
    await user.click(screen.getByRole('button', { name: 'Record fee' }))

    await waitFor(() => expect(recordFeeActual).toHaveBeenCalled())
    const sent = recordFeeActual.mock.calls[0][0]
    expect(sent.order_id).toBe('order-7')
    expect(sent.statement_period_start).toBe('2026-02-01')
    expect(sent.statement_period_end).toBe('2026-02-28')
    expect(sent).not.toHaveProperty('period_start')
  })

  it('shows the reason a 409 gives', async () => {
    recordFeeActual.mockRejectedValue(
      conflict('this order amount would take the period remainder below zero'),
    )
    const user = userEvent.setup({ delay: null })
    render(<FeeActualForm {...PROPS} />)

    await user.type(screen.getByLabelText('Fee category'), 'transaction')
    await user.type(screen.getByLabelText(/Amount/), '99.00')
    await user.click(screen.getByRole('button', { name: 'Record fee' }))

    const refused = await screen.findByTestId('fee-actual-refused')
    expect(refused).toHaveTextContent('conflicts')
    expect(refused).toHaveTextContent('remainder below zero')
  })

  it('refuses an amount that is not a decimal before sending it', async () => {
    const user = userEvent.setup({ delay: null })
    render(<FeeActualForm {...PROPS} />)

    await user.type(screen.getByLabelText('Fee category'), 'transaction')
    await user.type(screen.getByLabelText(/Amount/), '12.4.0')
    await user.click(screen.getByRole('button', { name: 'Record fee' }))

    expect(await screen.findByTestId('fee-actual-invalid')).toBeInTheDocument()
    expect(recordFeeActual).not.toHaveBeenCalled()
  })

  it('shows a member the form, disabled, with no way to submit', () => {
    render(<FeeActualForm {...PROPS} canEdit={false} />)

    expect(screen.getByLabelText('Fee category')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Record fee' })).not.toBeInTheDocument()
    expect(screen.getByTestId('fee-actual-read-only')).toBeInTheDocument()
  })
})
