/**
 * ProvenanceBadge — where a figure came from, and whether to still believe it.
 *
 * FR-001 asks that every numeric input show its origin. FR-005 adds that a
 * hand measurement past the operator's threshold be flagged **while still
 * showing its last value**: hiding a stale figure leaves the cost
 * unexplained, and showing it without the flag leaves a three-year-old
 * measurement looking current. Both are worse than showing it and saying so.
 *
 * ## Why this is a component and not four lines in each panel
 *
 * The cost breakdown, the provenance list and the proposal list all label a
 * figure's origin, and they must agree about what the labels mean — a figure
 * called "Assumed" on one screen and "Estimated" on another reads as two
 * different things (Constitution III). The wording itself lives in
 * `lib/provenance`, which this renders.
 */

import { AlertTriangle, Clock } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { SOURCE_EXPLANATION, SOURCE_LABEL, SOURCE_VARIANT } from '@/lib/provenance'
import { formatShare } from '@/lib/money'
import { cn } from '@/lib/utils'
import type { ProvenanceSource } from '@/types/pricing'

export interface ProvenanceBadgeProps {
  source: ProvenanceSource
  /** The day the figure was established. Null means nothing was recorded. */
  asOf?: string | null
  /** True for a hand measurement past the tenant's threshold (FR-005). */
  isStale?: boolean
  /** True where an observation disputes this figure and waits review (FR-042e). */
  hasPendingRevision?: boolean
  /** True where the registry's default applied because nothing was recorded. */
  isDefault?: boolean
  /**
   * How far to believe an observed figure, a fraction in (0, 1] (T259). Shown
   * beside the origin; omitted where confidence means nothing.
   */
  confidence?: string | null
  /** Drops the date and the explanatory text, for a dense table cell. */
  compact?: boolean
  className?: string
}

/**
 * The date, or an explicit statement that there is none.
 *
 * Never a blank. A blank date reads as missing data on the screen, where "no
 * date" is itself the fact: nobody has recorded this figure.
 */
function dateLabel(asOf: string | null | undefined, isDefault: boolean): string {
  if (asOf) return `as of ${asOf}`
  return isDefault ? 'never recorded' : 'no date recorded'
}

export function ProvenanceBadge({
  source,
  asOf = null,
  isStale = false,
  hasPendingRevision = false,
  isDefault = false,
  confidence = null,
  compact = false,
  className,
}: ProvenanceBadgeProps) {
  return (
    <span
      className={cn('inline-flex flex-wrap items-center gap-1.5', className)}
      data-testid={`provenance-${source}`}
    >
      <Badge
        variant={isStale ? 'warning' : SOURCE_VARIANT[source]}
        title={SOURCE_EXPLANATION[source]}
      >
        {SOURCE_LABEL[source]}
      </Badge>

      {!compact && (
        <span className="text-xs text-muted-foreground">{dateLabel(asOf, isDefault)}</span>
      )}

      {/* US6/AC1: an observed figure says how much evidence stands behind it. */}
      {confidence && (
        <span
          className="text-xs text-muted-foreground"
          data-testid="provenance-confidence"
          title="From how many outcomes stand behind this figure and how closely they agree"
        >
          {formatShare(confidence)} confidence
        </span>
      )}

      {/* FR-005: flagged, and the figure above it is still shown. The badge
          says the measurement is old; it does not replace the value, because
          an operator with an old number can still judge it and an operator
          with no number cannot. */}
      {isStale && (
        <Badge
          variant="outline"
          className="gap-1 border-yellow-500/50 text-yellow-700 dark:text-yellow-500"
          data-testid="provenance-stale"
          title="This measurement is older than your staleness threshold. The figure is still in use — re-measure it to be sure of the cost."
        >
          <Clock className="h-3 w-3" aria-hidden="true" />
          Stale
        </Badge>
      )}

      {/* FR-042e: a divergence nobody is told about is one nobody acts on.
          Pricing keeps using the current figure while this is pending, which
          the title says so nobody assumes the new reading is already in use. */}
      {hasPendingRevision && (
        <Badge
          variant="outline"
          className="gap-1 border-blue-500/50 text-blue-700 dark:text-blue-400"
          data-testid="provenance-pending-revision"
          title="An observation disagrees with this figure and is waiting for your review. Pricing still uses the current figure."
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          Review waiting
        </Badge>
      )}
    </span>
  )
}
