/**
 * The one place the frontend reads a product's make-cost.
 *
 * Three screens show this figure -- the product list, the product detail page
 * and the channel pricing editor -- and they used to reach it three different
 * ways: the list read `total_make_cost` off the list payload, the detail page
 * read `cost_breakdown.total_make_cost` and parsed it to a float, and the
 * pricing editor received that float as a prop. An operator comparing two
 * screens had no way to know which figure to trust (Constitution III).
 *
 * The backend sends money as an exact decimal string. `parseFloat` turns it
 * into a binary float, which is the one conversion that can make two screens
 * showing the same cost disagree in the last cent. So the accessor returns the
 * **string**, and the float conversion happens once, at the formatter, where it
 * only affects display.
 */

/** A money amount as an exact decimal string, e.g. "20.30". */
export type MoneyString = string

/** Either shape the API serves a cost in. */
export interface MakeCostSource {
  /** Present on the list payload. */
  total_make_cost?: MoneyString | null
  /** Present on the detail payload. */
  cost_breakdown?: { total_make_cost?: MoneyString | null } | null
}

/** The string shown when the API sent no cost at all. */
export const NO_COST = '0'

/**
 * The product's total make-cost, as the exact decimal string the API sent.
 *
 * Prefers the structured breakdown when the payload carries one, because that
 * is the authoritative shape; falls back to the list field. Both are produced
 * by the same engine call, so they agree -- the preference only decides which
 * is read, not which is right.
 */
export function makeCostOf(product: MakeCostSource | null | undefined): MoneyString {
  if (!product) return NO_COST
  const fromBreakdown = product.cost_breakdown?.total_make_cost
  if (fromBreakdown !== undefined && fromBreakdown !== null && fromBreakdown !== '') {
    return fromBreakdown
  }
  const fromList = product.total_make_cost
  if (fromList !== undefined && fromList !== null && fromList !== '') {
    return fromList
  }
  return NO_COST
}

/**
 * The make-cost as a number, for arithmetic the UI does on top of it
 * (suggested prices, averages). Rounding and float error here affect a
 * derived suggestion, never the cost the operator is shown.
 */
export function makeCostNumber(product: MakeCostSource | null | undefined): number {
  const parsed = Number.parseFloat(makeCostOf(product))
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * Whether two payloads report the same make-cost, compared as written rather
 * than as floats. Used by the tests that hold the three screens together.
 */
export function sameMakeCost(
  a: MakeCostSource | null | undefined,
  b: MakeCostSource | null | undefined,
): boolean {
  return normaliseMoney(makeCostOf(a)) === normaliseMoney(makeCostOf(b))
}

/**
 * Compare decimal strings by value, so "20.30" and "20.3" are the same figure
 * while staying out of floating point.
 */
export function normaliseMoney(value: MoneyString): string {
  const trimmed = value.trim()
  if (!/^-?\d*(\.\d*)?$/.test(trimmed) || trimmed === '' || trimmed === '-') return trimmed
  const negative = trimmed.startsWith('-')
  const [whole, fraction = ''] = trimmed.replace('-', '').split('.')
  const cleanWhole = whole.replace(/^0+(?=\d)/, '') || '0'
  const cleanFraction = fraction.replace(/0+$/, '')
  const body = cleanFraction ? `${cleanWhole}.${cleanFraction}` : cleanWhole
  return negative && body !== '0' ? `-${body}` : body
}
