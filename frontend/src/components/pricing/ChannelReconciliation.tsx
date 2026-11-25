/**
 * ChannelReconciliation — what the channel charged against what we planned.
 *
 * Two figures an operator could not see before, and one distinction the screen
 * is built around:
 *
 * * **Planned against recorded** (FR-041d), per fee category, with the
 *   unallocated remainder shown rather than hidden. A difference the operator
 *   cannot attribute to a category is a difference they cannot act on.
 * * **Periodic costs absorbed over actual order volume** (FR-025). A slow
 *   month makes the subscription expensive per order, and that is the point of
 *   showing it. Where there were no orders at all the cost is reported as
 *   **unabsorbed** — not divided by zero, and not reported as free.
 *
 * The distinction: "nothing recorded" is not "agrees with plan". A channel
 * nobody has reconciled shows a dash, because a zero difference would claim a
 * reconciliation that never happened.
 *
 * Sales tax appears only as a liability, never in revenue or profit
 * (FR-028c, FR-028d).
 */

import { AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { formatMoney, formatPercent } from '@/lib/money'
import { MarginFigure } from './MarginBasisLabel'
import type { ChannelPnL } from '@/types/pricing'

interface ChannelReconciliationProps {
  pnl: ChannelPnL
  currencySymbol?: string
  className?: string
}

/** One labelled figure, with an optional note under it. */
function Figure({
  label,
  value,
  note,
  testId,
  tone = 'default',
}: {
  label: string
  value: string
  note?: string
  testId?: string
  tone?: 'default' | 'muted' | 'negative'
}) {
  return (
    <div data-testid={testId}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          'mt-0.5 font-medium tabular-nums',
          tone === 'muted' && 'text-muted-foreground',
          tone === 'negative' && 'text-destructive',
        )}
      >
        {value}
      </dd>
      {note ? <p className="mt-0.5 text-xs text-muted-foreground">{note}</p> : null}
    </div>
  )
}

export function ChannelReconciliation({
  pnl,
  currencySymbol = '$',
  className,
}: ChannelReconciliationProps) {
  const symbol = currencySymbol
  const noOrders = pnl.order_count === 0
  const shippingLoss = pnl.shipping_net.trim().startsWith('-')

  return (
    <div className={cn('space-y-4', className)} data-testid="channel-reconciliation">
      <Card>
        <CardHeader>
          <CardTitle>Channel profitability</CardTitle>
          <CardDescription>
            {pnl.period_start} to {pnl.period_end} &middot;{' '}
            {pnl.order_count === 1 ? '1 order' : `${pnl.order_count} orders`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Figure
              label="Revenue (tax-exclusive)"
              value={formatMoney(pnl.revenue_tax_exclusive, symbol)}
              testId="pnl-revenue"
            />
            <Figure
              label="Planned fees"
              value={formatMoney(pnl.planned_fee_total, symbol)}
              testId="pnl-planned-fees"
            />
            <Figure
              label="Recorded fees"
              value={
                pnl.actual_fee_total === null
                  ? '—'
                  : formatMoney(pnl.actual_fee_total, symbol)
              }
              note={pnl.actual_fee_total === null ? 'nothing reconciled yet' : undefined}
              tone={pnl.actual_fee_total === null ? 'muted' : 'default'}
              testId="pnl-actual-fees"
            />
            <Figure
              label="Shipping revenue"
              value={formatMoney(pnl.shipping_revenue, symbol)}
              testId="pnl-shipping-revenue"
            />
            <Figure
              label="Postage paid"
              value={formatMoney(pnl.postage_paid, symbol)}
              testId="pnl-postage"
            />
            <Figure
              label="Shipping, net"
              value={formatMoney(pnl.shipping_net, symbol)}
              note={shippingLoss ? 'shipping cost more than it earned' : undefined}
              tone={shippingLoss ? 'negative' : 'default'}
              testId="pnl-shipping-net"
            />
          </dl>

          <div className="flex flex-wrap items-baseline justify-between gap-3 border-t pt-4">
            <div>
              <p className="text-xs text-muted-foreground">Profit</p>
              <p className="mt-0.5 text-2xl font-semibold tabular-nums" data-testid="pnl-profit">
                {formatMoney(pnl.profit, symbol)}
              </p>
            </div>
            <MarginFigure
              marginPct={pnl.margin_pct}
              basis={pnl.margin_basis}
              label={pnl.margin_basis_label}
              emphasis
            />
          </div>

          {/* Tax: a liability, never revenue (FR-028c, FR-028d). */}
          {pnl.sales_tax_collected !== '0.00' && pnl.sales_tax_collected !== '0' ? (
            <div className="rounded-md border bg-muted/40 p-3" data-testid="pnl-tax">
              <p className="text-sm font-medium">Sales tax</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatMoney(pnl.sales_tax_collected, symbol)} collected,{' '}
                {formatMoney(pnl.sales_tax_liability, symbol)} owed. Tax is never counted
                as revenue or profit above, whoever remits it.
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Absorption (FR-025) */}
      {pnl.absorbed_costs.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Costs not charged per sale</CardTitle>
            <CardDescription>
              Subscriptions and listing fees, spread over the orders that actually
              arrived.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cost</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Orders</TableHead>
                  <TableHead className="text-right">Per order</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pnl.absorbed_costs.map((cost) => (
                  <TableRow key={cost.key} data-testid={`absorbed-${cost.key}`}>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{cost.label}</span>
                        {cost.is_unabsorbed ? (
                          <Badge
                            variant="warning"
                            data-testid={`absorbed-unabsorbed-${cost.key}`}
                          >
                            Unabsorbed
                          </Badge>
                        ) : null}
                      </div>
                      {cost.is_unabsorbed ? (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          no orders in this period to absorb it over — the cost was still
                          owed
                        </p>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(cost.total, symbol)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {cost.order_count}
                    </TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      data-testid={`absorbed-per-order-${cost.key}`}
                    >
                      {cost.per_order === null ? '—' : formatMoney(cost.per_order, symbol)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {noOrders ? (
              <div
                className="mt-3 flex items-start gap-2 rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3"
                data-testid="pnl-no-orders"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-yellow-600" />
                <p className="text-xs">
                  This period has no orders, so {formatMoney(pnl.unabsorbed_total, symbol)}{' '}
                  of periodic cost could not be absorbed. A channel that sold nothing has
                  not become free.
                </p>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* Reconciliation (FR-041d) */}
      <Card>
        <CardHeader>
          <CardTitle>Planned against recorded</CardTitle>
          <CardDescription>
            What the fee rules predicted, against what the statement charged. A
            category recorded but never planned is a fee you are paying and have not
            modelled.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pnl.reconciliation.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="reconciliation-empty">
              No fees planned and none recorded for this period.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Planned</TableHead>
                  <TableHead className="text-right">Recorded</TableHead>
                  <TableHead className="text-right">Unallocated</TableHead>
                  <TableHead className="text-right">Difference</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pnl.reconciliation.map((row) => {
                  const unreconciled = row.actual_total === null
                  const overrun =
                    row.unallocated_remainder !== null &&
                    row.unallocated_remainder.trim().startsWith('-')
                  return (
                    <TableRow key={row.category} data-testid={`reconcile-${row.category}`}>
                      <TableCell>
                        <span className="font-medium">{row.category}</span>
                        {overrun ? (
                          <p
                            className="mt-0.5 text-xs text-destructive"
                            data-testid={`reconcile-overrun-${row.category}`}
                          >
                            order amounts exceed the period total — the period figure needs
                            correcting
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatMoney(row.planned, symbol)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right tabular-nums',
                          unreconciled && 'text-muted-foreground',
                        )}
                        data-testid={`reconcile-actual-${row.category}`}
                      >
                        {unreconciled ? '—' : formatMoney(row.actual_total, symbol)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right tabular-nums',
                          overrun && 'text-destructive',
                        )}
                      >
                        {row.unallocated_remainder === null
                          ? '—'
                          : formatMoney(row.unallocated_remainder, symbol)}
                      </TableCell>
                      <TableCell
                        className="text-right tabular-nums"
                        data-testid={`reconcile-difference-${row.category}`}
                      >
                        {unreconciled ? (
                          <span className="text-muted-foreground">not reconciled</span>
                        ) : (
                          <>
                            {formatMoney(row.difference, symbol)}
                            {row.difference_pct_of_fee !== null ? (
                              <span className="ml-1 text-xs text-muted-foreground">
                                ({formatPercent(row.difference_pct_of_fee)})
                              </span>
                            ) : null}
                          </>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
