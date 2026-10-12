/**
 * How each fee basis reads to an operator, and which ones are counts.
 *
 * These live in their own module rather than beside the table that uses them
 * because a component file that also exports constants breaks fast refresh —
 * the same reason `lib/money` is separate. They are also shared between the
 * breakdown table and the rule editor, which is the other reason.
 */

import type { FeeBasis } from '@/types/pricing'

/** How each basis reads to an operator, in the words they would use. */
export const BASIS_LABEL: Record<FeeBasis, string> = {
  item_subtotal: 'Item price',
  item_plus_shipping: 'Item + shipping',
  order_total: 'Order total',
  per_listing: 'Per listing',
  per_order: 'Per order',
  per_unit_sold: 'Per unit sold',
  per_month: 'Per month',
}

/**
 * What each basis means for the operator's money, in their own terms.
 *
 * Shown beside the choice rather than hidden in a tooltip: the basis is the
 * decision that decides whether a fee moves when the price does, and it is the
 * one most easily got wrong.
 */
export const BASIS_CONSEQUENCE: Record<FeeBasis, string> = {
  item_subtotal: 'moves with the item price only',
  item_plus_shipping: 'moves with the item price and the shipping you charge',
  order_total: 'moves with everything the customer paid',
  per_listing: 'charged per listing, whether or not it sells',
  per_order: 'charged once per order, whatever it contains',
  per_unit_sold: 'charged for every unit on the line',
  per_month: 'charged monthly, absorbed over the orders you get',
}

/**
 * Bases that are a count rather than an amount.
 *
 * A percentage of a quantity is not an amount, so a rule on one of these
 * carries its charge in its fixed amount and the backend refuses a rate.
 */
export const COUNT_BASES: ReadonlySet<FeeBasis> = new Set<FeeBasis>([
  'per_listing',
  'per_order',
  'per_unit_sold',
  'per_month',
])

/** The order the bases are offered in: the most commonly charged first. */
export const BASES_IN_ORDER: FeeBasis[] = [
  'item_plus_shipping',
  'item_subtotal',
  'order_total',
  'per_order',
  'per_unit_sold',
  'per_listing',
  'per_month',
]
