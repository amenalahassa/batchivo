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

/**
 * Which amount a margin percentage is taken over. These are the backend's own
 * values (`tenant_pricing_policy.margin_basis`): `customer_total` reproduces
 * today's definition and is the default, so switching is opt-in.
 */
export type MarginBasis = 'customer_total' | 'item_price' | 'net_revenue'

/** How overhead reaches a unit of production. */
export type OverheadMethod = 'per_machine_hour' | 'percentage'

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

/**
 * The tenant's pricing policy, as `GET /settings/pricing-policy` serves it.
 *
 * `origin` is `legacy_settings` for a tenant the Tier 1 migration has not
 * reached: their figures come from the old settings blob and are a fallback,
 * not a decision anyone made. Say so on screen rather than presenting it as
 * configured.
 */
export interface PricingPolicy {
  print_labor_rate: Money
  finishing_labor_rate: Money
  default_machine_rate_per_hour: Money | null
  overhead_method: OverheadMethod
  overhead_monthly_pool: Money | null
  expected_monthly_machine_hours: Money | null
  /**
   * Overhead absorbed per machine-hour, or null when no pool and capacity are
   * declared — reported missing rather than as zero.
   */
  overhead_rate_per_machine_hour: Money | null
  overhead_percentage: Percent
  electricity_rate_per_kwh: Money | null
  margin_basis: MarginBasis
  default_target_margin_pct: Percent | null
  rounding_rule: string | null
  sales_tax_recoverable: boolean
  staleness_threshold_days: number
  margin_alert_threshold_pct: Percent
  min_outcomes_before_auto_update: number
  estimate_divergence_threshold_pct: Percent
  origin: 'policy_row' | 'legacy_settings'
  effective_from: string | null
  effective_to: string | null
  set_by_role: string | null
}

/** A change to one or more policy levers. Unlisted levers are carried forward. */
export type PricingPolicyUpdate = Partial<
  Pick<
    PricingPolicy,
    | 'print_labor_rate'
    | 'finishing_labor_rate'
    | 'default_machine_rate_per_hour'
    | 'overhead_method'
    | 'overhead_monthly_pool'
    | 'expected_monthly_machine_hours'
    | 'electricity_rate_per_kwh'
    | 'margin_basis'
    | 'default_target_margin_pct'
    | 'rounding_rule'
    | 'sales_tax_recoverable'
    | 'staleness_threshold_days'
    | 'margin_alert_threshold_pct'
    | 'min_outcomes_before_auto_update'
    | 'estimate_divergence_threshold_pct'
  >
> & { effective_from?: string }

/**
 * A printer's machine cost policy and the hourly rate it implies.
 *
 * `machine_rate_per_hour` is null when nothing could be derived. Render that
 * as unknown, never as zero: a zero makes a 40-hour print look free.
 * `missing` names the inputs the operator has not supplied.
 */
export interface PrinterCostPolicy {
  printer_id: string
  purchase_price: Money | null
  expected_lifetime_hours: number | null
  maintenance_reserve_total: Money | null
  measured_watts: Money | null
  /** This printer's own rate; null when it falls back to the tenant policy's. */
  electricity_rate_per_kwh: Money | null
  /** The rate actually used, whether the printer's own or the tenant's. */
  effective_electricity_rate_per_kwh: Money | null
  machine_rate_per_hour: Money | null
  /** The parts the rate is made of, each named, so it needs no recomputing. */
  components: Record<string, Money>
  missing: string[]
}

export type PrinterCostPolicyUpdate = Partial<
  Pick<
    PrinterCostPolicy,
    | 'purchase_price'
    | 'expected_lifetime_hours'
    | 'maintenance_reserve_total'
    | 'measured_watts'
    | 'electricity_rate_per_kwh'
  >
>

/** One spool's share of a purchase, and what a usable gram of it cost. */
export interface SpoolLandedCost {
  spool_id: string
  spool_label: string | null
  purchase_price: Money | null
  allocated_shipping: Money
  allocated_tax: Money
  tax_recoverable: boolean
  nominal_weight_grams: Money
  unusable_remainder_grams: Money
  /** Nominal weight less the unusable remainder — never the nominal weight. */
  usable_weight_grams: Money
  total_landed_cost: Money | null
  cost_per_gram: Money | null
  /** True when weights were unusable and shipping was split evenly instead. */
  even_split_fallback: boolean
  incomplete_reasons: string[]
  /** How the figure was arrived at, in order. Show it; do not make them ask. */
  derivation: string[]
}

/** A filament purchase, with the landed cost it implies for each of its spools. */
export interface FilamentPurchase {
  id: string
  supplier: string | null
  purchase_date: string
  inbound_shipping_cost: Money
  tax_amount: Money
  tax_recoverable: boolean
  order_reference: string | null
  notes: string | null
  spools: SpoolLandedCost[]
  allocation_notes: string[]
}

export interface FilamentPurchaseCreate {
  supplier?: string | null
  purchase_date: string
  inbound_shipping_cost?: Money
  tax_amount?: Money
  tax_recoverable?: boolean
  order_reference?: string | null
  notes?: string | null
}

export type FilamentPurchaseUpdate = Partial<FilamentPurchaseCreate>

export interface FilamentPurchaseListResponse {
  purchases: FilamentPurchase[]
  total: number
  skip: number
  limit: number
}
