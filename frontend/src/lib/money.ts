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
export function formatMoney(
  amount: Money | null | undefined,
  symbol = '$',
  { places = 2 }: { places?: number } = {},
): string {
  if (amount === null || amount === undefined || amount === '') return '—'

  const negative = amount.trim().startsWith('-')
  const [whole, fraction = ''] = amount.trim().replace(/^[-+]/, '').split('.')
  let cents = fraction.slice(0, places).padEnd(places, '0')

  // Round the discarded tail up, in string space.
  if (fraction.length > places && Number.parseInt(fraction[places], 10) >= 5) {
    const bumped = (Number.parseInt(cents || '0', 10) + 1).toString()
    if (bumped.length > places) {
      const carried = (Number.parseInt(whole || '0', 10) + 1).toString()
      return `${negative ? '-' : ''}${symbol}${carried}${places > 0 ? `.${'0'.repeat(places)}` : ''}`
    }
    cents = bumped.padStart(places, '0')
  }

  if (places === 0) return `${negative ? '-' : ''}${symbol}${whole || '0'}`
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

/**
 * Exact arithmetic on the decimal strings the API sends.
 *
 * `formatMoney` above keeps *rendering* out of floating point, but a screen
 * that multiplies a unit cost by a quantity, or sums a few line totals, was
 * still doing it with `parseFloat` and JavaScript numbers — the thing
 * Constitution IV rules out for a monetary value. `0.07 * 3` is
 * `0.21000000000000002`, and a line total that reads a cent off the sum of its
 * parts is the defect that makes an operator stop trusting the screen.
 *
 * So these work on scaled `BigInt`s: a decimal string is split into its digits
 * and its scale, the arithmetic is integer, and the result comes back as a
 * decimal string with every digit it earned. Nothing rounds until the
 * formatter, which is the one place rounding is allowed to happen.
 *
 * They are deliberately only the three operations a *display* needs — add,
 * multiply by a count, and average a set. A price, a margin or a fee is the
 * engine's to compute (Constitution III); none of it belongs here.
 */

/** A decimal string split into integer digits and the scale they are at. */
interface Scaled {
  digits: bigint
  scale: number
}

const DECIMAL = /^[-+]?(\d+(\.\d*)?|\.\d+)$/

function toScaled(amount: string): Scaled | null {
  const trimmed = amount.trim()
  if (!DECIMAL.test(trimmed)) return null

  const negative = trimmed.startsWith('-')
  const [whole, fraction = ''] = trimmed.replace(/^[-+]/, '').split('.')
  const digits = BigInt(`${whole || '0'}${fraction}` || '0')
  return { digits: negative ? -digits : digits, scale: fraction.length }
}

function fromScaled({ digits, scale }: Scaled): Money {
  const negative = digits < 0n
  const absolute = (negative ? -digits : digits).toString().padStart(scale + 1, '0')
  const whole = absolute.slice(0, absolute.length - scale)
  const fraction = scale > 0 ? absolute.slice(absolute.length - scale) : ''
  const body = fraction ? `${whole}.${fraction}` : whole
  return negative ? `-${body}` : body
}

/** Both figures at the larger of their two scales, so they can be added. */
function align(a: Scaled, b: Scaled): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale)
  return [
    a.digits * 10n ** BigInt(scale - a.scale),
    b.digits * 10n ** BigInt(scale - b.scale),
    scale,
  ]
}

/** Zero, written at no scale: the identity for `sumMoney`. */
export const ZERO: Money = '0'

/**
 * The sum of two decimal strings, exactly, at the wider of their scales.
 *
 * An unreadable amount contributes nothing rather than `NaN`: a malformed
 * figure must not turn a whole column into a dash, and `formatMoney` already
 * shows a missing amount as one.
 */
export function addMoney(a: Money | null | undefined, b: Money | null | undefined): Money {
  const left = a ? toScaled(a) : null
  const right = b ? toScaled(b) : null
  if (!left) return right ? fromScaled(right) : ZERO
  if (!right) return fromScaled(left)

  const [x, y, scale] = align(left, right)
  return fromScaled({ digits: x + y, scale })
}

/** The sum of a column, exactly. An empty column sums to zero, not a dash. */
export function sumMoney(values: Array<Money | null | undefined>): Money {
  return values.reduce<Money>((total, value) => addMoney(total, value), ZERO)
}

/**
 * The difference between two decimal strings, exactly — `a` less `b`.
 *
 * A difference is the one figure a *comparison* needs, and the comparison this
 * exists for is actual against theoretical: `actual - theoretical` says which
 * way a production run went and by how much. Doing it as
 * `parseFloat(a) - parseFloat(b)` is how a variance of exactly zero comes out
 * as `-1.4e-17` and renders as a cost overrun on a run that matched plan.
 *
 * A missing figure on either side contributes nothing, in keeping with
 * `addMoney`: a column must not collapse because one cell is unreadable.
 */
export function subtractMoney(a: Money | null | undefined, b: Money | null | undefined): Money {
  const left = a ? toScaled(a) : null
  const right = b ? toScaled(b) : null
  if (!left) return right ? fromScaled({ digits: -right.digits, scale: right.scale }) : ZERO
  if (!right) return fromScaled(left)

  const [x, y, scale] = align(left, right)
  return fromScaled({ digits: x - y, scale })
}

/**
 * A decimal string times a quantity, exactly — a line total.
 *
 * The factor is a quantity rather than a second amount: a whole count of
 * components, or a measured weight in grams. It is accepted as a number for
 * the callers that hold a count as one, and converted through its own decimal
 * representation rather than multiplied as a float, so a per-gram cost times
 * 142.5 g lands on the same digits the engine computed (FR-047).
 */
export function multiplyMoney(
  amount: Money | null | undefined,
  factor: number | string,
): Money {
  const left = amount ? toScaled(amount) : null
  const right = toScaled(typeof factor === 'number' ? factor.toString() : factor)
  if (!left || !right) return ZERO
  return fromScaled({ digits: left.digits * right.digits, scale: left.scale + right.scale })
}

/**
 * Order two decimal strings by value: -1, 0 or 1, with null last.
 *
 * Picking the best of several margins by `parseFloat(a) > parseFloat(b)` can
 * order two figures wrongly when they differ below the float's precision, and
 * the consequence is not a rounding error -- it is the screen naming the wrong
 * channel as the best one. The comparison is integer, so it cannot.
 *
 * An unreadable or missing figure sorts below every real one: "no margin" is
 * not "the best margin".
 */
export function compareMoney(a: Money | null | undefined, b: Money | null | undefined): number {
  const left = a ? toScaled(a) : null
  const right = b ? toScaled(b) : null
  if (!left && !right) return 0
  if (!left) return -1
  if (!right) return 1

  const [x, y] = align(left, right)
  if (x < y) return -1
  if (x > y) return 1
  return 0
}

/**
 * An amount split `divisor` ways, to `places`, half-up.
 *
 * Division is the one operation here that cannot be exact — a third of a penny
 * is not a penny — so it rounds, and it says where. Doing it in one integer
 * division means that is the *only* rounding: there is no intermediate result
 * to round twice.
 *
 * Dividing by zero, or by something that is not a figure, has no answer, so it
 * returns null and the caller shows a dash rather than a zero.
 */
export function divideMoney(
  amount: Money | null | undefined,
  divisor: number | string,
  places = 2,
): Money | null {
  const left = amount ? toScaled(amount) : null
  const right = toScaled(typeof divisor === 'number' ? divisor.toString() : divisor)
  if (!left || !right || right.digits === 0n) return null

  // round(left / 10^leftScale / (right / 10^rightScale), places)
  const numerator = left.digits * 10n ** BigInt(places + right.scale)
  const denominator = right.digits * 10n ** BigInt(left.scale)
  const negative = numerator < 0n !== denominator < 0n
  const absoluteNumerator = numerator < 0n ? -numerator : numerator
  const absoluteDenominator = denominator < 0n ? -denominator : denominator

  let quotient = absoluteNumerator / absoluteDenominator
  if ((absoluteNumerator % absoluteDenominator) * 2n >= absoluteDenominator) quotient += 1n

  return fromScaled({ digits: negative ? -quotient : quotient, scale: places })
}

/**
 * The mean of a set of figures, to `places`, half-up.
 *
 * A summary of figures the engine produced, never an input to anything: an
 * average of per-channel margins is a reading aid, and nothing is priced from
 * it. An empty set has no mean, so it returns null and the caller shows a dash.
 */
export function averageMoney(
  values: Array<Money | null | undefined>,
  places = 2,
): Money | null {
  const usable = values.filter((value): value is Money => {
    return value !== null && value !== undefined && value !== '' && toScaled(value) !== null
  })
  if (usable.length === 0) return null
  return divideMoney(sumMoney(usable), usable.length, places)
}
