/**
 * CostBreakdownPanel — what a unit costs to make, and why anyone should
 * believe the figure.
 *
 * Three rules this panel exists to keep:
 *
 * 1. **Every line names its origin and its date** (FR-001, FR-018). A reader
 *    must be able to tell a measured figure from a guess without leaving the
 *    screen.
 * 2. **Nothing missing is shown as zero** (FR-019). An incompletely costed
 *    item says what is missing; a zero would be indistinguishable from a real
 *    figure and makes a 9-hour print look free.
 * 3. **Money is rendered from the decimal string the API sent.** No Number(),
 *    no toFixed() on a parsed float (Constitution IV) — see `lib/money`.
 */

import { AlertTriangle, Info } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { formatMoney, formatShare } from '@/lib/money'
import { isStaleMeasurement } from '@/lib/provenance'
import { ProvenanceBadge } from './ProvenanceBadge'
import type { CostBreakdown, CostLine, ProvenanceSource } from '@/types/pricing'

interface CostBreakdownPanelProps {
  breakdown: CostBreakdown
  /** Currency symbol to prefix amounts with. The API sends no currency. */
  currencySymbol?: string
  /**
   * The tenant's staleness threshold in days, from the pricing policy.
   *
   * Omitted, no line is flagged stale. That is the right default: inventing a
   * threshold here would flag figures against a number the operator never
   * set, and FR-005 makes the threshold theirs.
   */
  stalenessThresholdDays?: number | null
  className?: string
}

function LineRow({
  line,
  symbol,
  stalenessThresholdDays,
}: {
  line: CostLine
  symbol: string
  stalenessThresholdDays?: number | null
}) {
  const source = (line.source as ProvenanceSource) ?? 'assumed'
  const stale = isStaleMeasurement(line, stalenessThresholdDays)
  return (
    <div
      className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-2"
      data-testid={`cost-line-${line.key}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{line.label}</span>
          <Badge variant={line.risk_class === 'at_risk' ? 'outline' : 'secondary'}>
            {line.risk_class === 'at_risk' ? 'At risk' : 'Not at risk'}
          </Badge>
        </div>
        <div className="mt-0.5">
          {/* The shared badge, so "Assumed" means the same thing here as on
              the provenance list and the proposal list (Constitution III). */}
          <ProvenanceBadge
            source={source}
            asOf={line.as_of}
            isStale={stale}
            isDefault={!line.as_of}
            hasPendingRevision={line.has_pending_revision ?? false}
            confidence={line.confidence ?? null}
          />
        </div>
      </div>
      {/* The amount stays beside the badge even when the figure is stale: an
          operator with an old number can still judge it, and one with no
          number cannot (FR-005). */}
      <span className="tabular-nums font-medium">{formatMoney(line.amount, symbol)}</span>
    </div>
  )
}

export function CostBreakdownPanel({
  breakdown,
  currencySymbol = '$',
  stalenessThresholdDays = null,
  className,
}: CostBreakdownPanelProps) {
  const symbol = currencySymbol
  const isIncomplete = breakdown.incomplete_reasons.length > 0
  const staleLines = breakdown.lines.filter((line) =>
    isStaleMeasurement(line, stalenessThresholdDays),
  )
  const hasPremium = breakdown.failure_premium !== '0' && formatMoney(breakdown.failure_premium, '') !== '0.00'

  return (
    <Card className={className} data-testid="cost-breakdown-panel">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2">
          <span>Make cost</span>
          <span className="tabular-nums" data-testid="total-make-cost">
            {formatMoney(breakdown.total_make_cost, symbol)}
          </span>
        </CardTitle>
        <CardDescription>
          {formatShare(breakdown.observed_share)} of this cost rests on observed or measured
          figures; {formatShare(breakdown.assumed_share)} is still assumed.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {isIncomplete && (
          <div
            className="rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3"
            data-testid="incomplete-costing"
            role="alert"
          >
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              <span>Incompletely costed</span>
            </div>
            <ul className="mt-1 list-disc space-y-0.5 pl-6 text-sm">
              {breakdown.incomplete_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}

        {/* FR-005. Named lines rather than a count: "2 figures are stale"
            sends the reader hunting, and the point of the warning is to tell
            them what to re-measure. The cost is still shown and still used. */}
        {staleLines.length > 0 && (
          <div
            className="rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3 text-sm"
            data-testid="stale-measurements"
            role="status"
          >
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              <span>
                {staleLines.length === 1
                  ? 'One measurement is older than your threshold'
                  : `${staleLines.length} measurements are older than your threshold`}
              </span>
            </div>
            <p className="mt-1 text-muted-foreground">
              This cost still uses {staleLines.length === 1 ? 'it' : 'them'}. Re-measure{' '}
              {staleLines.map((line) => line.label).join(', ')} to be sure of the figure — your
              threshold is {stalenessThresholdDays} days.
            </p>
          </div>
        )}

        {breakdown.lines.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="no-cost-lines">
            Nothing is costed yet — this item has no material, labor or machine time recorded.
          </p>
        ) : (
          <div className="divide-y">
            {breakdown.lines.map((line) => (
              <LineRow
                key={line.key}
                line={line}
                symbol={symbol}
                stalenessThresholdDays={stalenessThresholdDays}
              />
            ))}
          </div>
        )}

        <Separator />

        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">At risk of failure</dt>
            <dd className="tabular-nums" data-testid="at-risk-subtotal">
              {formatMoney(breakdown.at_risk_subtotal, symbol)}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Spent after the part is good</dt>
            <dd className="tabular-nums" data-testid="not-at-risk-subtotal">
              {formatMoney(breakdown.not_at_risk_subtotal, symbol)}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">
              Failure premium at {formatShare(breakdown.yield_applied)} yield
              <span className="ml-1 text-xs">
                ({breakdown.failure_mode === 'per_plate' ? 'per plate' : 'per part'})
              </span>
            </dt>
            <dd className="tabular-nums" data-testid="failure-premium">
              {formatMoney(breakdown.failure_premium, symbol)}
            </dd>
          </div>
        </dl>

        {!hasPremium && (
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>
              No failure premium: this item is costed at a perfect yield, so nothing is added
              for reprints.
            </span>
          </p>
        )}
      </CardContent>
    </Card>
  )
}
