/**
 * CostBreakdownSection — the breakdown, fetched, on a product or a model page.
 *
 * `CostBreakdownPanel` renders a breakdown it is handed. This fetches one and
 * deals with the three states a fetch has, so the two pages that show a cost
 * do not each grow their own copy of that handling — and so neither drifts
 * into showing a figure the other does not (Constitution III, SC-008).
 *
 * It also supplies the staleness threshold from the tenant's pricing policy,
 * which is what lets the panel flag a hand-measured figure as stale (FR-005).
 * The threshold is the operator's, never a constant invented here.
 *
 * ## Why a product and a model share one component
 *
 * FR-018 asks the same thing of both: every line itemised, each with its
 * origin. The engine already answers both through one service; a second
 * presentation would be the same divergence in a different layer.
 */

import { AlertCircle, Loader2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CostBreakdownPanel } from './CostBreakdownPanel'
import { ProvenanceFieldsPanel } from './ProvenanceFieldsPanel'
import { useModelCost, usePricingPolicy, useProductCost } from '@/hooks/usePricing'

export interface CostBreakdownSectionProps {
  /** Show a sellable product's make-cost. Mutually exclusive with `modelId`. */
  productId?: string
  /** Show one printed item's make-cost. Mutually exclusive with `productId`. */
  modelId?: string
  /** Cost the model on a specific printer, at that machine's rate (FR-011). */
  printerId?: string
  currencySymbol?: string
  className?: string
}

export function CostBreakdownSection({
  productId,
  modelId,
  printerId,
  currencySymbol = '$',
  className,
}: CostBreakdownSectionProps) {
  // Both hooks are gated on their own id, so exactly one fetch happens. They
  // are called unconditionally because hooks must be (rules-of-hooks).
  const product = useProductCost(productId)
  const model = useModelCost(modelId, printerId)
  const { policy } = usePricingPolicy()

  const active = productId ? product : model
  const { breakdown, isLoading, error } = active

  if (isLoading) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Make cost</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Working out what this costs to make…
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error || !breakdown) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Make cost</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>No cost to show</AlertTitle>
            <AlertDescription>
              {/*
                An empty figure beats a wrong one: FR-019 says an item missing
                an input is reported as incompletely costed, never costed at
                zero, and the same holds when the request itself failed.
              */}
              {error instanceof Error
                ? error.message
                : 'The cost could not be worked out just now.'}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className={className}>
      <CostBreakdownPanel
        breakdown={breakdown}
        currencySymbol={currencySymbol}
        stalenessThresholdDays={policy?.staleness_threshold_days ?? null}
      />
      {/* Each input behind the lines, and the one place to re-confirm a stale
          measurement (T259, FR-001, FR-005). Closed by default: the lines
          above already say each one's weakest origin. */}
      <details className="mt-2 rounded-md border px-3 py-2" data-testid="cost-inputs">
        <summary className="cursor-pointer text-sm font-medium">
          Where these figures come from
        </summary>
        <div className="pt-2">
          <ProvenanceFieldsPanel
            entityType={productId ? 'product' : 'model'}
            entityId={(productId ?? modelId) as string}
          />
        </div>
      </details>
    </div>
  )
}
