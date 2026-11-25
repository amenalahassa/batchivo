/**
 * The compact form of "this cost is a floor, not a cost".
 *
 * `CostBreakdownPanel` shows the same fact in full, as a bordered block
 * listing every reason -- which is right on a detail screen and far too much
 * for a table row. But the list screens are where a product is picked, so an
 * item missing its print time or its machine rate has to say so there too,
 * rather than showing a finished-looking figure built from a zero (FR-019).
 *
 * One component for both lists, so the wording an operator learns on the
 * product list is the wording they meet on the model list.
 */

import { AlertTriangle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

export interface IncompleteCostBadgeProps {
  /** What the engine could not cost, as the API reported it. */
  reasons: string[] | null | undefined
  className?: string
}

/**
 * Nothing at all when the costing is complete -- an always-present badge
 * saying "complete" would train the operator to ignore the row.
 */
export function IncompleteCostBadge({ reasons, className }: IncompleteCostBadgeProps) {
  if (!reasons || reasons.length === 0) return null

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={`border-yellow-200 bg-yellow-500/10 text-yellow-700 ${className ?? ''}`}
            data-testid="incomplete-cost-badge"
            role="alert"
            // The reasons are on the trigger as well as in the tooltip: a
            // tooltip is hover-only on a pointer device and absent to a
            // screen reader that never focuses the badge.
            aria-label={`Incompletely costed: ${reasons.join('; ')}`}
          >
            <AlertTriangle className="mr-1 h-3 w-3" aria-hidden="true" />
            Incomplete
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="font-medium">Incompletely costed</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
