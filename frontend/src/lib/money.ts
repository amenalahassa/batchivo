/**
 * Presenting exact decimal money without ever becoming a float.
 *
 * Every amount the pricing API sends is a decimal **string** (Constitution IV:
 * exact decimal arithmetic end to end). `Number('0.023986666').toFixed(2)`
 * would work for most values and quietly fail for some, and the failure would
 * surface as a cost that drifts by a cent for reasons nobody can trace. So the
 * padding and rounding here are done in string space.
 *
 * These live in their own module rather than beside the panel that uses them
 * because a component file that also exports helpers breaks fast refresh.
 */

import type { Money } from '@/types/pricing'

/**
 * Render a decimal string as money, to two places.
 *
 * A missing amount is a dash, never a zero: an unknown cost and a free one are
 * different facts, and showing the second for the first is the defect FR-019
 * exists to prevent.
 */
export function formatMoney(amount: Money | null | undefined, symbol = '$'): string {
  if (amount === null || amount === undefined || amount === '') return '—'

  const negative = amount.trim().startsWith('-')
  const [whole, fraction = ''] = amount.trim().replace(/^[-+]/, '').split('.')
  let cents = fraction.slice(0, 2).padEnd(2, '0')

  // Round the discarded tail up, in string space.
  if (fraction.length > 2 && Number.parseInt(fraction[2], 10) >= 5) {
    const bumped = (Number.parseInt(cents, 10) + 1).toString()
    if (bumped.length > 2) {
      return `${negative ? '-' : ''}${symbol}${(Number.parseInt(whole, 10) + 1).toString()}.00`
    }
    cents = bumped.padStart(2, '0')
  }

  return `${negative ? '-' : ''}${symbol}${whole || '0'}.${cents}`
}

/** A share of "0.9200" reads as 92%. */
export function formatShare(fraction: Money | null | undefined): string {
  if (fraction === null || fraction === undefined || fraction === '') return '—'
  const value = Number.parseFloat(fraction)
  if (Number.isNaN(value)) return '—'
  return `${Math.round(value * 100)}%`
}

/**
 * Render a percentage as a screen shows it: one decimal place.
 *
 * The API sends four decimals ("35.2693") so no precision is lost on the wire;
 * a percentage is read, not added up, so one place is what a reader wants. The
 * rounding is done in string space for the same reason as `formatMoney`.
 *
 * A null percentage is "undefined", not "0%". The net-revenue basis with fees
 * consuming the whole amount has no percentage, and reporting that as zero
 * would read as break-even on a sale that lost money.
 */
export function formatPercent(
  value: Money | null | undefined,
  { places = 1, undefinedLabel = 'undefined' }: { places?: number; undefinedLabel?: string } = {},
): string {
  if (value === null || value === undefined || value === '') return undefinedLabel

  const trimmed = value.trim()
  const negative = trimmed.startsWith('-')
  const [whole, fraction = ''] = trimmed.replace(/^[-+]/, '').split('.')

  if (places === 0) {
    const rounded =
      fraction.length > 0 && Number.parseInt(fraction[0], 10) >= 5
        ? (Number.parseInt(whole || '0', 10) + 1).toString()
        : whole || '0'
    return `${negative ? '-' : ''}${rounded}%`
  }

  let kept = fraction.slice(0, places).padEnd(places, '0')
  if (fraction.length > places && Number.parseInt(fraction[places], 10) >= 5) {
    const bumped = (Number.parseInt(kept, 10) + 1).toString()
    if (bumped.length > places) {
      const carried = (Number.parseInt(whole || '0', 10) + 1).toString()
      return `${negative ? '-' : ''}${carried}.${'0'.repeat(places)}%`
    }
    kept = bumped.padStart(places, '0')
  }

  return `${negative ? '-' : ''}${whole || '0'}.${kept}%`
}

/**
 * The symbol for a currency code, for a figure that is not in the tenant's own
 * currency.
 *
 * A sales channel carries its own `currency_code` (FR-020), so a tenant who
 * reports in GBP may have a channel that settles in CAD. Rendering that
 * channel's fees with the tenant's symbol would state an amount in the wrong
 * currency, which is a worse error than an unfamiliar prefix. An unmapped code
 * therefore falls back to the code itself: "CHF 20.30" is plainer than a
 * guessed glyph, and unlike a glyph it cannot be wrong.
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  GBP: '£',
  USD: '$',
  EUR: '€',
  CAD: 'CA$',
  AUD: 'A$',
  NZD: 'NZ$',
  JPY: '¥',
}

export function symbolForCurrency(code: string | null | undefined, fallback = '$'): string {
  if (!code) return fallback
  const upper = code.trim().toUpperCase()
  if (upper === '') return fallback
  return CURRENCY_SYMBOLS[upper] ?? `${upper} `
}
