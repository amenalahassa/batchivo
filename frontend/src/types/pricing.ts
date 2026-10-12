/**
 * TypeScript types for the pricing and costing API.
 * These mirror the Pydantic schemas in backend/app/schemas/model.py
 * (CostLine, CostBreakdown) and the breakdown shape in
 * specs/002-pricing-engine-rebuild/data-model.md.
 *
 * Money crosses the wire as a decimal **string**, never a JSON number
 * (Constitution IV: exact decimal arithmetic end to end). A number here would
 * reintroduce binary floating point at the last possible moment, which is
 * exactly where it is hardest to notice. Parse with a decimal library or render
 * the string directly; do not call Number() on these fields.
 */

/** A money amount as an exact decimal string, e.g. "20.30". */
export type Money = string

/** A percentage as an exact decimal string, e.g. "35.3". */
export type Percent = string

/**
 * Whether a cost is exposed to print failure. The failure premium is applied
 * only to the at-risk portion: packaging materials and packing labor are spent
 * on a part already known good, so they are never at risk.
 */
export type RiskClass = 'at_risk' | 'not_at_risk'

/**
 * Where a figure came from. `observed` and `measured` carry evidence;
 * `assumed` is a guess the system supplied and `policy` is an operator
 * decision. A reader needs this to know how much to trust the number
 * (Constitution VI).
 */
export type ProvenanceSource = 'policy' | 'observed' | 'measured' | 'assumed'

/** How a yield figure is interpreted when a plate holds more than one print. */
export type FailureMode = 'per_part' | 'per_plate'

/** Which denominator a margin percentage is taken over. */
export type MarginBasis = 'on_price' | 'on_net_revenue' | 'on_cost'

/** The known cost line keys, in the order they are presented. */
export type CostLineKey =
  | 'material'
  | 'waste'
  | 'machine'
  | 'overhead'
  | 'labor_handling'
  | 'labor_finishing'
  | 'labor_packing'
  | 'packaging'
  | 'components'
  | 'child_products'

/** One line of a cost breakdown, with its amount, risk class and provenance. */
export interface CostLine {
  key: CostLineKey | string
  label: string
  amount: Money
  risk_class: RiskClass
  /** Where the inputs behind this line came from. */
  source: ProvenanceSource
  /** ISO 8601 date the figure was set or observed. */
  as_of: string | null
}

/**
 * A full make-cost breakdown. Recomputed on demand and never stored as an
 * authoritative figure (Constitution V), except as a once-written snapshot on
 * a settled order line.
 */
export interface CostBreakdown {
  lines: CostLine[]

  /** Subtotals by risk class; the failure premium applies to the at-risk one. */
  at_risk_subtotal: Money
  not_at_risk_subtotal: Money

  /** The yield figure actually applied, as a fraction in (0, 1]. */
  yield_applied: Money
  failure_mode: FailureMode
  /** The amount the yield figure added to the at-risk subtotal. */
  failure_premium: Money

  total_make_cost: Money

  /** Share of the cost whose inputs are observed or measured, 0-1. */
  observed_share: Money
  /** Share of the cost still resting on assumptions, 0-1. */
  assumed_share: Money

  /**
   * What was missing, if anything. A non-empty list means the figure is
   * incompletely costed and must be presented as such -- never silently
   * costed at zero.
   */
  incomplete_reasons: string[]
}

/** A margin percentage always travels with the basis it was taken on. */
export interface MarginFigure {
  margin_percentage: Percent
  margin_basis: MarginBasis
  profit: Money
}
