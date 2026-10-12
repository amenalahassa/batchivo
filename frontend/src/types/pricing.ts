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

/* ===========================================================================
 * Channel economics: the real fee stack, shipping and tax (User Story 3)
 * ======================================================================== */

/**
 * What a fee is charged on. Each is an amount or a count taken from the order
 * and never another fee — there is no fee on a fee (research.md D9).
 */
export type FeeBasis =
  | 'item_subtotal'
  | 'item_plus_shipping'
  | 'order_total'
  | 'per_listing'
  | 'per_order'
  | 'per_unit_sold'
  | 'per_month'

/** Which clamp changed a fee's amount, if either did (FR-021c). */
export type ClampApplied = 'min' | 'max'

/** Who hands the sales tax to the revenue authority (FR-028b). */
export type TaxRemitter = 'marketplace' | 'operator'

/**
 * One fee as charged, with everything behind it.
 *
 * `clamp_applied` is the field that stops a capped fee reading as a
 * miscalculated one (FR-021c), and `is_expected` separates what a channel
 * charges on average from what it charged here (FR-029). Both must reach the
 * screen; a breakdown that hides them is a breakdown nobody can check.
 */
export interface FeeCharge {
  name: string
  basis: FeeBasis
  amount: Money
  clamp_applied: ClampApplied | null
  is_expected: boolean
  rate_pct: Percent
  fixed_amount: Money
  /** The amount or count the rate was applied to. */
  basis_amount: Money
  incidence_pct: Percent | null
}

/** One fee rule as the operator configures it. */
export interface FeeRule {
  id: string
  tenant_id: string
  sales_channel_id: string
  name: string
  basis: FeeBasis
  rate_pct: Percent
  fixed_amount: Money
  min_amount: Money | null
  max_amount: Money | null
  incidence_pct: Percent | null
  sort_order: number
  applies_from: string
  applies_to: string | null
}

export interface FeeRuleCreate {
  name: string
  basis: FeeBasis
  rate_pct?: Percent
  fixed_amount?: Money
  min_amount?: Money | null
  max_amount?: Money | null
  incidence_pct?: Percent | null
  sort_order?: number
  applies_from: string
  applies_to?: string | null
}

export type FeeRuleUpdate = Partial<FeeRuleCreate>

export interface FeeRuleListResponse {
  rules: FeeRule[]
  total: number
  as_of: string
}

/** A hypothetical order, for inspecting the stack without creating one. */
export interface FeePreviewRequest {
  item_subtotal: Money
  shipping_revenue?: Money
  extras?: Money
  quantity?: number
  listings?: number
  sales_tax_collected?: Money
  amounts_are_tax_inclusive?: boolean
  as_of?: string
}

export interface FeePreviewResponse {
  charges: FeeCharge[]
  total: Money
  /** Per-listing and per-month rules, absorbed over a period instead (FR-025). */
  periodic: FeeCharge[]
  periodic_total: Money
  bound_clamps: string[]
  as_of: string
  revenue_tax_exclusive: Money
  tax_exclusive_derived: boolean
}

/** Postage the operator pays, by zone and weight bracket (FR-024). */
export interface ShippingProfile {
  id: string
  tenant_id: string
  name: string
  destination_zone: string
  weight_bracket_min_grams: Money
  weight_bracket_max_grams: Money | null
  postage_cost: Money
  carrier: string | null
  effective_from: string
}

export interface ShippingProfileCreate {
  name: string
  destination_zone: string
  weight_bracket_min_grams?: Money
  weight_bracket_max_grams?: Money | null
  postage_cost: Money
  carrier?: string | null
  effective_from: string
}

export type ShippingProfileUpdate = Partial<ShippingProfileCreate>

export interface ShippingProfileListResponse {
  profiles: ShippingProfile[]
  total: number
}

/** A reserve held against revenue: neither a fee nor a cost (FR-026). */
export interface RevenueDeduction {
  key: string
  label: string
  amount: Money
  rate_pct: Percent
  basis_amount: Money
}

/**
 * What one unit earns on one channel at the price in effect.
 *
 * `margin_pct` is null rather than zero where the basis is zero — net revenue
 * after fees, with fees consuming the whole amount. Render that as undefined,
 * never as break-even.
 */
export interface ProductMargin {
  product_id: string
  sales_channel_id: string
  as_of: string

  list_price: Money
  shipping_revenue: Money
  postage_paid: Money
  /** Shipping revenue less postage paid, positive or negative (FR-024). */
  shipping_net: Money

  make_cost: Money
  fees: FeeCharge[]
  fee_total: Money
  deductions: RevenueDeduction[]
  deduction_total: Money

  net_revenue: Money
  profit: Money
  margin_pct: Percent | null
  margin_basis: MarginBasis
  margin_basis_label: string
  margin_basis_amount: Money

  sales_tax_collected: Money
  sales_tax_liability: Money
  tax_remitter: TaxRemitter
  /** True when the exclusive amounts were derived from inclusive ones (FR-028e). */
  tax_exclusive_derived: boolean
  revenue_tax_exclusive: Money

  observed_share: Money | null
  assumed_share: Money | null
  incomplete_reasons: string[]
}

/** A recorded fee: exactly one of a period scope or an order scope. */
export interface FeeActualCreate {
  sales_channel_id: string
  fee_category: string
  amount: Money
  period_start?: string
  period_end?: string
  order_id?: string
}

export interface FeeActual {
  id: string
  tenant_id: string
  sales_channel_id: string
  fee_category: string
  amount: Money
  period_start: string | null
  period_end: string | null
  order_id: string | null
  /** `entered` by a human, never presented as observed (FR-041e). */
  source: string
}

/** Plan against statement for one fee category (FR-041d). */
export interface CategoryReconciliation {
  category: string
  planned: Money
  actual_period: Money | null
  actual_order_scoped: Money
  unallocated_remainder: Money | null
  actual_total: Money | null
  /** Null while nothing is recorded — which is not the same as agreeing. */
  difference: Money | null
  difference_pct_of_fee: Percent | null
}

/** A periodic cost spread over the period's order volume (FR-025). */
export interface AbsorbedCost {
  key: string
  label: string
  total: Money
  order_count: number
  /** Null when there were no orders to absorb it over. */
  per_order: Money | null
  is_unabsorbed: boolean
}

/** One channel over one period. */
export interface ChannelPnL {
  channel_id: string
  period_start: string
  period_end: string
  order_count: number

  revenue_tax_exclusive: Money
  sales_tax_collected: Money
  sales_tax_liability: Money

  postage_paid: Money
  shipping_revenue: Money
  shipping_net: Money

  planned_fee_total: Money
  actual_fee_total: Money | null
  unallocated_remainder: Money
  fee_difference: Money | null
  reconciliation: CategoryReconciliation[]

  absorbed_costs: AbsorbedCost[]
  unabsorbed_total: Money

  make_cost_total: Money
  profit: Money
  margin_pct: Percent | null
  margin_basis: MarginBasis
  margin_basis_label: string
}

/** Channel economics as the sales-channel form edits them. */
export interface ChannelEconomics {
  tax_remitter: TaxRemitter
  expected_discount_pct: Percent
  expected_refund_pct: Percent
  free_shipping_threshold: Money | null
  rounding_rule: string | null
  currency_code: string
  offsite_ads_opt_in: boolean
}

// ---------------------------------------------------------------------------
// The target-margin solver and the price ladder (tasks T089, T089b)
//
// `machine_hours` and every amount below is a decimal string, like everything
// else in this file. Nothing here parses one into a number: see `lib/money`.
// ---------------------------------------------------------------------------

/** Rounding rules the solver understands (FR-033). Every one rounds up. */
export type RoundingRule =
  | 'nearest_cent'
  | 'nearest_five_cents'
  | 'nearest_dollar'
  | 'psychological_99'
  | 'psychological_95'

/** What the operator asks for: a target margin, on a hypothetical sale. */
export interface PriceSolveRequest {
  target_margin_pct: Percent
  quantity?: number
  shipping_revenue?: Money
  extras?: Money
  margin_basis?: MarginBasis | null
  apply_rounding?: boolean
  rounding_rule?: RoundingRule | string | null
  snap_to_free_shipping?: boolean
  as_of?: string | null
}

/**
 * One deliberate move away from the solved price (FR-033).
 *
 * A rounding rule and a free-shipping snap both change the answer. Neither is
 * a correction, so neither is hidden: each says where the price came from and
 * where it went, which is the only way an operator can check it.
 */
export interface PriceAdjustment {
  key: string
  label: string
  from_price: Money
  to_price: Money
  delta: Money
}

/**
 * The solver's answer, and everything behind it (FR-032 - FR-035).
 *
 * `achievable` is false, with `reason` of `"unachievable"` and every price
 * field null, where no price achieves the target. The API serves that case as
 * a 422 carrying this shape in `detail`.
 *
 * `is_proposal` is always true. Nothing here has been published to any
 * channel: applying it is a separate write on the price (US4 scenario 5).
 */
export interface PriceSolveResult {
  product_id: string
  sales_channel_id: string
  as_of: string

  achievable: boolean
  reason: string | null
  binding_constraint: string | null

  target_margin_pct: Percent
  margin_basis: MarginBasis
  margin_basis_label: string

  /** The closed-form answer, before any rounding or snap. */
  required_price_raw: Money | null
  /** The price to charge: the raw price with every adjustment applied. */
  required_price_rounded: Money | null
  adjustments: PriceAdjustment[]
  /** Fees whose cap or floor bound at the price returned (FR-032a). */
  binding_clamps: string[]

  /** At or above the target, since every rounding rule rounds up. */
  margin_pct_at_price: Percent | null
  profit_at_price: Money | null

  make_cost: Money
  postage_paid: Money
  fees: FeeCharge[]

  /** Every figure the answer came from, rendered as strings (FR-034). */
  inputs: Record<string, string>
  passes: number
  is_proposal: boolean
}

/** One price point and what it earns (FR-007). No rung is recommended. */
export interface PriceLadderRung {
  price: Money
  /** Null where fees consume the whole basis, never zero. */
  margin_pct: Percent | null
  profit: Money
  margin_basis: MarginBasis
  /** Null when nobody has timed the print, never zero. */
  profit_per_machine_hour: Money | null
}

/**
 * Margin across a range of prices, for the operator to choose from.
 *
 * The bounds are echoed back because they were the caller's: the ladder has no
 * range of its own, since a default range's midpoint would function as a
 * recommended price while resting on nothing (FR-007).
 */
export interface PriceLadder {
  product_id: string
  sales_channel_id: string
  as_of: string

  price_from: Money
  price_to: Money
  step: Money

  margin_basis: MarginBasis
  margin_basis_label: string
  make_cost: Money
  postage_paid: Money
  machine_hours: Money | null

  rungs: PriceLadderRung[]
}

/** The range the operator asks the ladder for. No defaults (FR-007). */
export interface PriceLadderParams {
  price_from: Money
  price_to: Money
  step: Money
  quantity?: number
  shipping_revenue?: Money
  as_of?: string | null
}
