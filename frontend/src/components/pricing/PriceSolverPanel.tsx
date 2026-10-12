/**
 * PriceSolverPanel — state a target margin, receive the price that achieves it.
 *
 * The inverse of what the pricing editor does today: type a price, read a
 * margin, type another price. The arithmetic behind the inversion is not
 * something an operator can do with a calculator, because the percentage fees
 * a marketplace charges are charged on the very price being solved for.
 *
 * Three rules this panel exists to keep:
 *
 * 1. **The answer is a proposal, and nothing is published.** The operator
 *    applies it or rejects it (US4 scenario 5). `onApply` is the host's to
 *    implement as a write on the price; this component performs none, and
 *    renders nothing that implies one happened.
 * 2. **Every adjustment is shown as an adjustment** (FR-033). A rounding rule
 *    and a free-shipping snap both move the price, and a price that silently
 *    differs from the arithmetic is a price nobody can check — so the raw
 *    figure and each move are on screen beside the final one.
 * 3. **An unachievable target names its constraint, never a number** (FR-035).
 *    A plausible-looking price for an impossible target is the one output that
 *    would actually cost the operator money.
 *
 * Money is rendered from the decimal string the API sent — no Number(), no
 * toFixed on a parsed float (Constitution IV); see `lib/money`.
 */

import { useState } from 'react'
import { AlertTriangle, ArrowRight, Info, Lock } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { formatMoney, formatPercent } from '@/lib/money'
import { FeeBreakdownTable } from './FeeBreakdownTable'
import { MarginBasisLabel } from './MarginBasisLabel'
import type { PriceSolveRequest, PriceSolveResult } from '@/types/pricing'

interface PriceSolverPanelProps {
  /** The answer, once there is one. Undefined before the first solve. */
  result?: PriceSolveResult
  isSolving?: boolean
  /** Anything other than an unachievable target: a 404, a 500, a lost network. */
  error?: Error | null
  onSolve: (request: PriceSolveRequest) => void
  /**
   * Apply the proposal. Omitted, no apply control is rendered at all — which
   * is the correct state for a viewer, since applying a price is a write.
   */
  onApply?: (price: string) => void
  onDismiss?: () => void
  currencySymbol?: string
  className?: string
}

/** The price currently in effect, for the proposal to be compared against. */
const DEFAULT_TARGET = '35'

function AdjustmentRow({
  label,
  from,
  to,
  symbol,
  testId,
}: {
  label: string
  from: string
  to: string
  symbol: string
  testId: string
}) {
  return (
    <div
      className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-1.5 text-sm"
      data-testid={testId}
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-1.5 tabular-nums">
        <span className="text-muted-foreground line-through">{formatMoney(from, symbol)}</span>
        <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
        <span className="font-medium">{formatMoney(to, symbol)}</span>
      </span>
    </div>
  )
}

export function PriceSolverPanel({
  result,
  isSolving = false,
  error = null,
  onSolve,
  onApply,
  onDismiss,
  currencySymbol = '$',
  className,
}: PriceSolverPanelProps) {
  const symbol = currencySymbol
  const [target, setTarget] = useState(DEFAULT_TARGET)
  const [applyRounding, setApplyRounding] = useState(true)
  const [snapToFreeShipping, setSnapToFreeShipping] = useState(true)

  const trimmed = target.trim()
  // Validated as a decimal string rather than parsed: a target is money-like
  // and goes to the API as the operator typed it (Constitution IV).
  const targetLooksValid = /^\d+(\.\d+)?$/.test(trimmed) && trimmed !== '' && Number(trimmed) < 100

  const handleSolve = () => {
    if (!targetLooksValid) return
    onSolve({
      target_margin_pct: trimmed,
      apply_rounding: applyRounding,
      snap_to_free_shipping: snapToFreeShipping,
    })
  }

  const unachievable = result !== undefined && !result.achievable

  return (
    <Card className={className} data-testid="price-solver-panel">
      <CardHeader>
        <CardTitle>What should I charge?</CardTitle>
        <CardDescription>
          State the margin you want and the price that achieves it is solved against the fees
          charged on that very price. The answer is a proposal — nothing is published to the
          channel until you apply it.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[10rem] flex-1">
            <Label htmlFor="target-margin-pct">Target margin %</Label>
            <Input
              id="target-margin-pct"
              inputMode="decimal"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              aria-invalid={!targetLooksValid}
              data-testid="target-margin-input"
            />
          </div>
          <Button
            onClick={handleSolve}
            disabled={isSolving || !targetLooksValid}
            data-testid="solve-button"
          >
            {isSolving ? 'Solving…' : 'Solve'}
          </Button>
        </div>

        {!targetLooksValid && trimmed !== '' ? (
          <p className="text-sm text-destructive" data-testid="target-invalid">
            Enter a margin between 0 and 100.
          </p>
        ) : null}

        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <div className="flex items-center gap-2">
            <Switch
              id="apply-rounding"
              checked={applyRounding}
              onCheckedChange={setApplyRounding}
              data-testid="apply-rounding-switch"
            />
            <Label htmlFor="apply-rounding" className="font-normal">
              Apply my rounding rule
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="snap-free-shipping"
              checked={snapToFreeShipping}
              onCheckedChange={setSnapToFreeShipping}
              data-testid="snap-free-shipping-switch"
            />
            <Label htmlFor="snap-free-shipping" className="font-normal">
              Lift to the free-shipping threshold
            </Label>
          </div>
        </div>

        {error ? (
          <Alert variant="destructive" data-testid="solver-error">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>That price could not be worked out</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : null}

        {/* FR-035: the constraint, in words, and no number anywhere. */}
        {unachievable ? (
          <Alert data-testid="unachievable-target">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>
              No price achieves {formatPercent(result.target_margin_pct, { places: 0 })}
            </AlertTitle>
            <AlertDescription>
              <p data-testid="binding-constraint">{result.binding_constraint}</p>
              <p className="mt-2 text-xs">
                Lower the target, reduce the make-cost, or renegotiate the fees — there is no
                price to charge that would reach this margin.
              </p>
            </AlertDescription>
          </Alert>
        ) : null}

        {result !== undefined && result.achievable ? (
          <div className="space-y-4" data-testid="solve-result">
            <Separator />

            <div className="space-y-1">
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className="text-3xl font-semibold tabular-nums"
                  data-testid="proposed-price"
                >
                  {formatMoney(result.required_price_rounded, symbol)}
                </span>
                <Badge variant="secondary" data-testid="proposal-badge">
                  Proposal
                </Badge>
              </div>
              {/* A div rather than a p: the basis label is a badge, and a
                  badge is a block element that may not live inside a p. */}
              <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-sm text-muted-foreground">
                <span>Earns</span>
                <span className="font-medium" data-testid="achieved-margin">
                  {formatPercent(result.margin_pct_at_price)}
                </span>
                <MarginBasisLabel
                  basis={result.margin_basis}
                  label={result.margin_basis_label}
                  short
                />
                <span>
                  — {formatMoney(result.profit_at_price, symbol)} of profit on a make-cost of{' '}
                  {formatMoney(result.make_cost, symbol)}.
                </span>
              </div>
            </div>

            {/* FR-033: the raw figure, and every move away from it. */}
            <div className="rounded-md border p-3" data-testid="adjustments">
              <AdjustmentRow
                label="Solved price, before any adjustment"
                from={result.required_price_raw ?? ''}
                to={result.required_price_raw ?? ''}
                symbol={symbol}
                testId="adjustment-raw"
              />
              {result.adjustments.length > 0 ? (
                <>
                  <Separator className="my-1" />
                  {result.adjustments.map((adjustment) => (
                    <AdjustmentRow
                      key={adjustment.key}
                      label={adjustment.label}
                      from={adjustment.from_price}
                      to={adjustment.to_price}
                      symbol={symbol}
                      testId={`adjustment-${adjustment.key}`}
                    />
                  ))}
                </>
              ) : (
                <p className="py-1 text-xs text-muted-foreground" data-testid="no-adjustments">
                  No rounding or threshold moved this price.
                </p>
              )}
            </div>

            {/* FR-032a: a capped fee must never read as a miscalculated one. */}
            {result.binding_clamps.length > 0 ? (
              <Alert data-testid="binding-clamps">
                <Lock className="h-4 w-4" />
                <AlertTitle>
                  {result.binding_clamps.length === 1
                    ? 'One fee has stopped scaling with the price'
                    : 'Some fees have stopped scaling with the price'}
                </AlertTitle>
                <AlertDescription>
                  {result.binding_clamps.join(', ')} —{' '}
                  {result.binding_clamps.length === 1 ? 'its cap or floor is' : 'their caps or floors are'}{' '}
                  binding at this price, so the fee no longer grows as the price does. The price
                  above was solved against the capped amount, not the rate.
                </AlertDescription>
              </Alert>
            ) : null}

            {result.fees.length > 0 ? (
              <div data-testid="solve-fee-stack">
                <h4 className="mb-2 text-sm font-medium">What the channel takes at this price</h4>
                <FeeBreakdownTable charges={result.fees} currencySymbol={symbol} />
              </div>
            ) : null}

            {/* FR-034: the price can be explained without re-deriving it. */}
            {Object.keys(result.inputs).length > 0 ? (
              <details className="rounded-md border p-3" data-testid="solve-inputs">
                <summary className="cursor-pointer text-sm font-medium">
                  Every figure behind this price
                </summary>
                <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
                  {Object.entries(result.inputs).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">{key.replace(/_/g, ' ')}</dt>
                      <dd className="tabular-nums">{value}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ) : null}

            <Alert data-testid="nothing-published">
              <Info className="h-4 w-4" />
              <AlertDescription>
                Nothing has been published to the channel. This price takes effect only when you
                apply it.
              </AlertDescription>
            </Alert>

            {onApply || onDismiss ? (
              <div className="flex flex-wrap gap-2">
                {onApply ? (
                  <Button
                    onClick={() => onApply(result.required_price_rounded as string)}
                    data-testid="apply-price-button"
                  >
                    Apply {formatMoney(result.required_price_rounded, symbol)}
                  </Button>
                ) : null}
                {onDismiss ? (
                  <Button variant="outline" onClick={onDismiss} data-testid="reject-price-button">
                    Reject
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
