/**
 * MarginBasisLabel — the basis that produced a percentage, beside it.
 *
 * FR-031b, and the reason it is a requirement rather than a nicety: the same
 * sale is 35.3% of the customer total and 42.2% of net revenue after fees.
 * Those are both true, and an operator comparing one against a competitor's
 * other is comparing nothing. A percentage without its basis is a number two
 * people will disagree about while both reading the same screen.
 *
 * So this component is deliberately small and deliberately mandatory: it goes
 * beside *every* margin percentage, and it renders from the label the API sent
 * rather than from a local lookup, so a basis added to the backend cannot show
 * up here as a blank.
 */

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { formatPercent } from '@/lib/money'
import type { MarginBasis, Percent } from '@/types/pricing'

/** Short wording for each basis, for a column header or a tight row. */
const SHORT_LABEL: Record<MarginBasis, string> = {
  customer_total: 'of customer total',
  item_price: 'of item price',
  net_revenue: 'of net revenue',
}

interface MarginBasisLabelProps {
  basis: MarginBasis
  /** The sentence the API sent. Preferred over the local short label. */
  label?: string | null
  /** Render the short form, for a table cell rather than a figure. */
  short?: boolean
  className?: string
}

/** The basis alone, as a badge. */
export function MarginBasisLabel({
  basis,
  label,
  short = false,
  className,
}: MarginBasisLabelProps) {
  const text = short ? SHORT_LABEL[basis] : (label ?? SHORT_LABEL[basis])

  return (
    <Badge
      variant="secondary"
      className={cn('font-normal', className)}
      data-testid="margin-basis-label"
      data-basis={basis}
    >
      {text}
    </Badge>
  )
}

interface MarginFigureProps {
  /** The percentage as the API sent it, or null where it is undefined. */
  marginPct: Percent | null
  basis: MarginBasis
  label?: string | null
  /** Larger type, for the headline figure on a pricing screen. */
  emphasis?: boolean
  className?: string
}

/**
 * A margin percentage that cannot be rendered without its basis.
 *
 * Prefer this over formatting a percentage by hand: the basis is not optional
 * here, so there is no way to put a bare number on screen by forgetting to
 * pass one.
 *
 * A null percentage reads "undefined", never "0%". The net-revenue basis with
 * fees consuming the whole amount has no percentage, and a zero there would
 * read as break-even on a sale that lost money.
 */
export function MarginFigure({
  marginPct,
  basis,
  label,
  emphasis = false,
  className,
}: MarginFigureProps) {
  const undefinedMargin = marginPct === null || marginPct === undefined

  return (
    <span
      className={cn('inline-flex flex-wrap items-baseline gap-2', className)}
      data-testid="margin-figure"
    >
      <span
        className={cn(
          'tabular-nums',
          emphasis ? 'text-2xl font-semibold' : 'font-medium',
          undefinedMargin && 'text-muted-foreground',
        )}
        data-testid="margin-percentage"
      >
        {formatPercent(marginPct, { undefinedLabel: 'Undefined' })}
      </span>
      <MarginBasisLabel basis={basis} label={label} />
      {undefinedMargin ? (
        <span className="text-xs text-muted-foreground">
          fees consume the whole basis, so there is no percentage to report
        </span>
      ) : null}
    </span>
  )
}
