/**
 * PriceLadder — margin at each of a range of prices, and no opinion on which.
 *
 * FR-007 is a restraint rather than a feature. What a customer will pay is not
 * derivable from any data this system holds: there is no competitor feed, no
 * demand curve, no willingness-to-pay signal. A single "recommended price"
 * would therefore be a figure resting on nothing, sitting on a screen beside
 * figures that are real — and an operator cannot tell the two apart once they
 * are formatted the same way.
 *
 * So this table shows what each price *earns* and stops there. Deliberately
 * absent, and absent by design rather than by omission:
 *
 * - no rung is highlighted, starred, ranked or called best;
 * - the rows are in price order, because any other order would rank them;
 * - nothing is written back when a row is clicked — `onChoose` hands the price
 *   to the host, and choosing is the operator's act, not the table's.
 *
 * The one thing the ladder does assert is that the figures are real: each
 * rung's margin is the one the margin endpoint reports at that price, computed
 * on the basis in effect and named with it (FR-031b).
 *
 * Money is rendered from the decimal string the API sent — no Number(), no
 * toFixed on a parsed float (Constitution IV); see `lib/money`.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { formatMoney, formatPercent } from '@/lib/money'
import { MarginBasisLabel } from './MarginBasisLabel'
import type { PriceLadder as PriceLadderData } from '@/types/pricing'

interface PriceLadderProps {
  ladder?: PriceLadderData
  isLoading?: boolean
  error?: Error | null
  /**
   * The price currently in effect, marked so the operator can see where they
   * stand. This is a fact about the listing, not a recommendation.
   */
  currentPrice?: string | null
  /**
   * Take this price. Omitted, the rows are read-only — the correct state for a
   * viewer, since setting a price is a write.
   */
  onChoose?: (price: string) => void
  currencySymbol?: string
  className?: string
}

export function PriceLadder({
  ladder,
  isLoading = false,
  error = null,
  currentPrice = null,
  onChoose,
  currencySymbol = '$',
  className,
}: PriceLadderProps) {
  const symbol = currencySymbol
  const showPerHour = ladder?.machine_hours !== null && ladder?.machine_hours !== undefined

  return (
    <Card className={className} data-testid="price-ladder">
      <CardHeader>
        <CardTitle>What each price would earn</CardTitle>
        <CardDescription>
          What a customer will pay is not something this system can work out — it holds no
          competitor prices and no demand data. So here is the margin at each price, and the
          choice stays yours.
        </CardDescription>
      </CardHeader>

      <CardContent>
        {error ? (
          <p className="text-sm text-destructive" data-testid="ladder-error">
            {error.message}
          </p>
        ) : null}

        {isLoading ? (
          <p className="text-sm text-muted-foreground" data-testid="ladder-loading">
            Working out what each price earns…
          </p>
        ) : null}

        {!isLoading && !error && ladder && ladder.rungs.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="ladder-empty">
            That range produced no prices to compare. Widen it or reduce the step.
          </p>
        ) : null}

        {ladder && ladder.rungs.length > 0 ? (
          <>
            <Table data-testid="ladder-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Price</TableHead>
                  {/* The basis sits on the column, not in the prose: every
                      percentage below it is taken on that basis, and FR-031b
                      wants it beside the figures rather than in a caption. */}
                  <TableHead className="text-right">
                    <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                      Margin
                      <MarginBasisLabel
                        basis={ladder.margin_basis}
                        label={ladder.margin_basis_label}
                        short
                      />
                    </span>
                  </TableHead>
                  <TableHead className="text-right">Profit</TableHead>
                  {showPerHour ? (
                    <TableHead className="text-right">Profit per machine-hour</TableHead>
                  ) : null}
                  {onChoose ? <TableHead className="w-0" /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {ladder.rungs.map((rung) => {
                  const isCurrent = currentPrice !== null && rung.price === currentPrice
                  return (
                    <TableRow
                      key={rung.price}
                      data-testid={`ladder-rung-${rung.price}`}
                      data-current={isCurrent ? 'true' : undefined}
                    >
                      <TableCell className="tabular-nums font-medium">
                        {formatMoney(rung.price, symbol)}
                        {isCurrent ? (
                          <span
                            className="ml-2 text-xs font-normal text-muted-foreground"
                            data-testid="current-price-marker"
                          >
                            current
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right tabular-nums',
                          rung.margin_pct === null && 'text-muted-foreground',
                        )}
                      >
                        {formatPercent(rung.margin_pct, { undefinedLabel: 'Undefined' })}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatMoney(rung.profit, symbol)}
                      </TableCell>
                      {showPerHour ? (
                        <TableCell
                          className={cn(
                            'text-right tabular-nums',
                            rung.profit_per_machine_hour === null && 'text-muted-foreground',
                          )}
                        >
                          {/* Null, never zero: an untimed print has no rate to
                              report, and a zero would read as one that earns
                              nothing per hour (FR-019). */}
                          {formatMoney(rung.profit_per_machine_hour, symbol)}
                        </TableCell>
                      ) : null}
                      {onChoose ? (
                        <TableCell className="text-right">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onChoose(rung.price)}
                            data-testid={`choose-${rung.price}`}
                          >
                            Use this
                          </Button>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>

            <p className="mt-3 text-xs text-muted-foreground" data-testid="ladder-footnote">
              Make-cost {formatMoney(ladder.make_cost, symbol)} and postage{' '}
              {formatMoney(ladder.postage_paid, symbol)} per unit, as at {ladder.as_of}.{' '}
              {showPerHour
                ? `Each unit occupies the machine for ${ladder.machine_hours} hours.`
                : 'Nobody has timed this print, so there is no per-hour figure to report.'}{' '}
              Nothing on this table has been saved.
            </p>
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
