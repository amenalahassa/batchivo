/**
 * MarginDivergencePanel — what settled lines actually earned, against plan.
 *
 * FR-042's second clause: the operator must be *alerted* when a product's
 * realised margin diverges from plan beyond a threshold they set. An endpoint
 * alone does not alert anybody, and neither does a warning in a worker's log:
 * before this panel existed, the operator set `margin_alert_threshold_pct` on
 * the screen beside this one and then heard nothing. The periodic sweep in
 * `app/tasks/margin_alerts.py` now emails them; this is what they open when
 * the email arrives, and what the console shows without one.
 *
 * ## What it must say, and why
 *
 * - **Which lines moved** (US7 scenario 3). Not that a product
 *   underperformed — that sends the operator through three screens to find out
 *   whether it was the fee schedule or the filament. "fees +1.80, material
 *   +0.42" is a decision they can make this afternoon.
 * - **Both percentages, on a named basis** (FR-031b). A margin means nothing
 *   without the basis it was taken on, and the two percentages must be on the
 *   same one to be comparable at all.
 * - **That nothing was changed.** A divergence is an observation about settled
 *   history, not a correction to it: no snapshot moved (FR-038) and no price
 *   changed. A reader who thinks a figure has already been adjusted will act
 *   on the wrong thing.
 *
 * An undefined percentage renders as a dash, never 0%: where fees consumed the
 * whole basis there is no margin to report, and "0%" reads as break-even on a
 * sale that lost money.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Loader2, TrendingDown } from 'lucide-react'

import { feeRulesApi } from '@/lib/api/feeRules'
import { useCurrency } from '@/hooks/useCurrency'
import { formatMoney, formatPercent } from '@/lib/money'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { MarginDivergence } from '@/types/pricing'

export interface MarginDivergencePanelProps {
  /** Narrow to one product's settled lines. */
  productId?: string
  /** Only orders placed on or after this date. */
  since?: string
  className?: string
}

/** `labor_handling` reads badly on a screen; "labor handling" does not. */
function movementLabel(key: string): string {
  return key.replace(/_/g, ' ')
}

function DivergenceRow({
  divergence,
  symbol,
}: {
  divergence: MarginDivergence
  symbol: string
}) {
  const name = divergence.product_name ?? divergence.product_id ?? 'Unnamed product'

  return (
    <div className="space-y-2 rounded-md border p-3" data-testid={`divergence-${divergence.order_item_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium">{name}</div>
          <div className="text-xs text-muted-foreground">
            {divergence.sold_on ? `sold ${divergence.sold_on}` : 'sale date unrecorded'} · on{' '}
            {movementLabel(divergence.margin_basis)}
          </div>
        </div>
        <Badge
          variant="outline"
          className={
            divergence.shortfall
              ? 'border-destructive/50 text-destructive'
              : 'border-green-500/50 text-green-700 dark:text-green-500'
          }
          data-testid="divergence-points"
        >
          {divergence.shortfall ? (
            <TrendingDown className="mr-1 h-3 w-3" aria-hidden="true" />
          ) : null}
          {divergence.divergence_points === null
            ? '—'
            : `${formatMoney(divergence.divergence_points, '', { places: 1 })} points`}
        </Badge>
      </div>

      {/* Both percentages, and which is which. */}
      <div className="flex flex-wrap items-baseline gap-2 text-sm">
        <span className="text-muted-foreground">Planned</span>
        <span className="tabular-nums font-medium" data-testid="divergence-planned">
          {formatPercent(divergence.planned_margin_pct, { undefinedLabel: '—' })}
        </span>
        <span aria-hidden="true">→</span>
        <span className="text-muted-foreground">realised</span>
        <span className="tabular-nums font-medium" data-testid="divergence-realised">
          {formatPercent(divergence.realised_margin_pct, { undefinedLabel: '—' })}
        </span>
        <span className="text-xs text-muted-foreground">
          ({formatMoney(divergence.planned_profit, symbol)} →{' '}
          {formatMoney(divergence.realised_profit, symbol)})
        </span>
      </div>

      {/* US7 scenario 3: which lines moved, heaviest first. */}
      {divergence.movements.length > 0 ? (
        <ul className="space-y-0.5 text-xs" data-testid="divergence-movements">
          {divergence.movements.map((movement) => (
            <li key={movement.key} className="flex flex-wrap items-baseline gap-2">
              <span className="capitalize text-muted-foreground">
                {movementLabel(movement.key)}
              </span>
              <span className="tabular-nums">
                {formatMoney(movement.planned, symbol)} → {formatMoney(movement.realised, symbol)}
              </span>
              <span
                className={`tabular-nums font-medium ${
                  movement.delta.trim().startsWith('-') ? 'text-green-700' : 'text-destructive'
                }`}
              >
                {movement.delta.trim().startsWith('-') ? '' : '+'}
                {formatMoney(movement.delta, symbol)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="divergence-no-movements">
          No cost line moved — check the revenue on this order.
        </p>
      )}
    </div>
  )
}

export function MarginDivergencePanel({
  productId,
  since,
  className,
}: MarginDivergencePanelProps) {
  const { currency } = useCurrency()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['margin-divergence', { productId, since, onlyAlerting: true }],
    // Only the lines past the operator's own threshold: this panel is the
    // alert, and an alert that lists everything is not one.
    queryFn: () =>
      feeRulesApi.getMarginDivergence({ productId, since, onlyAlerting: true }),
  })

  if (isLoading) {
    return (
      <Card className={className} data-testid="margin-divergence-loading">
        <CardContent className="flex items-center gap-2 py-8 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Comparing settled orders against the margins they were sold at…
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card className={className} data-testid="margin-divergence-error">
        <CardContent className="py-8 text-sm text-muted-foreground" role="alert">
          The realised margins could not be loaded. Nothing has been changed.
        </CardContent>
      </Card>
    )
  }

  const divergences = data?.divergences ?? []

  return (
    <Card className={className} data-testid="margin-divergence">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-primary" aria-hidden="true" />
          <span>Margins that diverged from plan</span>
          {divergences.length > 0 && (
            <Badge variant="outline" data-testid="divergence-count">
              {divergences.length}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          {divergences.length === 0
            ? `No settled line has diverged by more than your threshold of ${formatMoney(
                data?.threshold_points,
                '',
                { places: 1 },
              )} points.`
            : `These earned a different margin than they were sold at, by more than your threshold of ${formatMoney(
                data?.threshold_points,
                '',
                { places: 1 },
              )} points. Nothing has been changed — no price moved and no estimate was revised.`}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {divergences.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="no-divergences">
            Every settled line came in within your threshold.
          </p>
        ) : (
          divergences.map((divergence) => (
            <DivergenceRow
              key={divergence.order_item_id}
              divergence={divergence}
              symbol={currency.symbol}
            />
          ))
        )}
      </CardContent>
    </Card>
  )
}
