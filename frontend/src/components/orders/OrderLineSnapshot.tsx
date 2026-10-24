/**
 * OrderLineSnapshot — what a sale froze for one line, and what it could not
 * (T232).
 *
 * The rate a sale froze from the order's currency to the books' was stored as
 * a bare number, and nothing showed it: its date and origin were lost at the
 * moment of sale, though FR-028g wants the figure shown with its date and
 * FR-028h with its origin. The snapshot's own warnings -- a stale rate, no
 * rate, no cost breakdown -- were only logged, so nobody reading the order
 * later could see why its margin is incomplete. Both are on the line now.
 *
 * A line in the books' own currency froze no conversion and needs none: it
 * shows nothing here unless the snapshot left a warning.
 */

import { AlertTriangle } from 'lucide-react'

import type { OrderItem } from '@/lib/api/orders'

const SOURCE_LABELS: Record<string, string> = {
  // `app/models/fx_rate.py:FX_RATE_SOURCES`.
  service: 'fetched',
  manual: 'entered by hand',
}

interface OrderLineSnapshotProps {
  item: OrderItem
  /** The order's own currency, the rate's base. */
  orderCurrency: string
}

export function OrderLineSnapshot({ item, orderCurrency }: OrderLineSnapshotProps) {
  const warnings = item.snapshot_incomplete ?? []
  const converted =
    item.fx_rate != null &&
    item.fx_quote_currency != null &&
    item.fx_quote_currency.toUpperCase() !== orderCurrency.toUpperCase()

  if (!converted && warnings.length === 0) return null

  const source = item.fx_rate_source
    ? (SOURCE_LABELS[item.fx_rate_source] ?? item.fx_rate_source)
    : null

  return (
    <div className="mt-2 space-y-1 text-xs" data-testid={`order-line-snapshot-${item.id}`}>
      {converted && (
        <p className="text-muted-foreground" data-testid="order-line-fx">
          Rate frozen at sale: 1 {orderCurrency} = {item.fx_rate} {item.fx_quote_currency}
          {item.fx_rate_date ? `, for ${item.fx_rate_date}` : ''}
          {source ? `, ${source}` : ''}
          {item.fx_rate_is_stale && (
            <span className="ml-1 font-medium text-amber-600" data-testid="order-line-fx-stale">
              (older than the sale)
            </span>
          )}
        </p>
      )}
      {warnings.length > 0 && (
        <ul className="space-y-0.5 text-amber-700" data-testid="order-line-incomplete">
          {warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-1">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
