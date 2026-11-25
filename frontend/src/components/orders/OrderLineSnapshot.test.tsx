/**
 * An order line shows the rate it froze, with its date and origin, and what
 * its snapshot could not record (T232, FR-028g, FR-028h).
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { OrderLineSnapshot } from './OrderLineSnapshot'
import type { OrderItem } from '@/lib/api/orders'

function item(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    product_id: 'product-1',
    product_sku: 'DRG-001',
    product_name: 'Dragon',
    quantity: 1,
    unit_price: '25.00',
    total_price: '25.00',
    ...overrides,
  }
}

describe('OrderLineSnapshot', () => {
  it('shows the frozen rate with the day it was for and where it came from', () => {
    render(
      <OrderLineSnapshot
        orderCurrency="USD"
        item={item({
          fx_rate: '0.785000',
          fx_rate_date: '2026-10-01',
          fx_rate_source: 'service',
          fx_quote_currency: 'GBP',
          fx_rate_is_stale: false,
        })}
      />,
    )

    expect(screen.getByTestId('order-line-fx')).toHaveTextContent(
      '1 USD = 0.785000 GBP, for 2026-10-01, fetched',
    )
    expect(screen.queryByTestId('order-line-fx-stale')).not.toBeInTheDocument()
  })

  it('flags a stale rate and a hand-entered one, and shows the snapshot’s warnings', () => {
    render(
      <OrderLineSnapshot
        orderCurrency="USD"
        item={item({
          fx_rate: '0.79',
          fx_rate_date: '2026-09-28',
          fx_rate_source: 'manual',
          fx_quote_currency: 'GBP',
          fx_rate_is_stale: true,
          snapshot_incomplete: ['the exchange rate is from 2026-09-28, before this sale'],
        })}
      />,
    )

    expect(screen.getByTestId('order-line-fx')).toHaveTextContent('entered by hand')
    expect(screen.getByTestId('order-line-fx-stale')).toBeInTheDocument()
    expect(screen.getByTestId('order-line-incomplete')).toHaveTextContent(
      'the exchange rate is from 2026-09-28',
    )
  })

  it('says a line froze no rate rather than showing parity', () => {
    render(
      <OrderLineSnapshot
        orderCurrency="USD"
        item={item({
          fx_rate: null,
          snapshot_incomplete: ['no exchange rate was available for USD/GBP on 2026-10-01'],
        })}
      />,
    )

    expect(screen.queryByTestId('order-line-fx')).not.toBeInTheDocument()
    expect(screen.getByTestId('order-line-incomplete')).toHaveTextContent(
      'no exchange rate was available',
    )
  })

  it('shows nothing for a complete line in the books’ own currency', () => {
    const { container } = render(
      <OrderLineSnapshot
        orderCurrency="GBP"
        item={item({ fx_rate: '1', fx_quote_currency: 'GBP', snapshot_incomplete: [] })}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})
