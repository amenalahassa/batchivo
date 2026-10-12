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
