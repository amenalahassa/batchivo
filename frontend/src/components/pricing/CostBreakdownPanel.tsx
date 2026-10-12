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
import type { CostBreakdown, CostLine, ProvenanceSource } from '@/types/pricing'

interface CostBreakdownPanelProps {
  breakdown: CostBreakdown
  /** Currency symbol to prefix amounts with. The API sends no currency. */
  currencySymbol?: string
  className?: string
}

/** Human wording for each origin, and how much weight it carries. */
const SOURCE_LABEL: Record<ProvenanceSource, string> = {
  observed: 'Observed',
  measured: 'Measured',
  policy: 'Your setting',
  assumed: 'Assumed',
}

const SOURCE_VARIANT: Record<ProvenanceSource, 'success' | 'secondary' | 'warning'> = {
  observed: 'success',
  measured: 'success',
  policy: 'secondary',
  assumed: 'warning',
}

function LineRow({ line, symbol }: { line: CostLine; symbol: string }) {
  const source = (line.source as ProvenanceSource) ?? 'assumed'
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
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant={SOURCE_VARIANT[source]}>{SOURCE_LABEL[source]}</Badge>
          <span>{line.as_of ? `as of ${line.as_of}` : 'never recorded'}</span>
        </div>
      </div>
      <span className="tabular-nums font-medium">{formatMoney(line.amount, symbol)}</span>
    </div>
  )
}

export function CostBreakdownPanel({
  breakdown,
  currencySymbol = '$',
  className,
}: CostBreakdownPanelProps) {
  const symbol = currencySymbol
  const isIncomplete = breakdown.incomplete_reasons.length > 0
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

        {breakdown.lines.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="no-cost-lines">
            Nothing is costed yet — this item has no material, labor or machine time recorded.
          </p>
        ) : (
          <div className="divide-y">
            {breakdown.lines.map((line) => (
              <LineRow key={line.key} line={line} symbol={symbol} />
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
