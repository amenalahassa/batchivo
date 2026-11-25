import { apiClient } from '../api'
import type {
  CostBreakdown,
  EntityProvenance,
  EstimateRevision,
  EstimateRevisionList,
  FieldOrigin,
  FilamentPurchase,
  FilamentPurchaseCreate,
  FilamentPurchaseListResponse,
  FilamentPurchaseUpdate,
  ModelCostProfile,
  ModelCostProfileUpdate,
  PricingPolicy,
  PricingPolicyUpdate,
  PriceLadder,
  PriceLadderParams,
  PriceSolveRequest,
  PriceSolveResult,
  PrinterCostPolicy,
  PrinterCostPolicyUpdate,
  ProvenanceWriteRequest,
  RevisionState,
  ScenarioRun,
  ScenarioRunList,
  ScenarioRunRequest,
} from '@/types/pricing'

/**
 * Pricing and costing API client.
 *
 * Every money field in these payloads is a decimal **string** and stays one:
 * nothing here parses an amount into a number (Constitution IV). Components
 * render the string or hand it to a decimal library.
 */
export const pricingApi = {
  /**
   * The itemised make-cost of one printed item.
   *
   * `printerId` costs the item at the rate of the machine it is planned on;
   * omitted, the policy's default machine rate applies.
   */
  getModelCost: async (modelId: string, printerId?: string): Promise<CostBreakdown> => {
    const query = printerId ? `?printer_id=${encodeURIComponent(printerId)}` : ''
    return apiClient.get<CostBreakdown>(`/api/v1/models/${modelId}/cost${query}`)
  },

  /** The itemised make-cost of one sellable unit, bundles included. */
  getProductCost: async (productId: string): Promise<CostBreakdown> => {
    return apiClient.get<CostBreakdown>(`/api/v1/products/${productId}/cost`)
  },

  /**
   * The pricing policy in effect, today or on `asOf`.
   *
   * An `asOf` read answers "what was the labor rate when this order was
   * placed", which is the question the policy table exists for.
   */
  getPricingPolicy: async (asOf?: string): Promise<PricingPolicy> => {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
    return apiClient.get<PricingPolicy>(`/api/v1/settings/pricing-policy${query}`)
  },

  /**
   * Change one or more levers. Requires admin or owner.
   *
   * This writes a new effective row rather than editing one, so the rate a
   * past order was costed at stays readable.
   */
  updatePricingPolicy: async (changes: PricingPolicyUpdate): Promise<PricingPolicy> => {
    return apiClient.put<PricingPolicy>('/api/v1/settings/pricing-policy', changes)
  },

  /** A printer's machine cost policy, with the rate's component parts. */
  getPrinterCostPolicy: async (printerId: string): Promise<PrinterCostPolicy> => {
    return apiClient.get<PrinterCostPolicy>(`/api/v1/printers/${printerId}/cost-policy`)
  },

  /** Set a printer's machine cost policy. Fields left out are not touched. */
  updatePrinterCostPolicy: async (
    printerId: string,
    changes: PrinterCostPolicyUpdate,
  ): Promise<PrinterCostPolicy> => {
    return apiClient.put<PrinterCostPolicy>(
      `/api/v1/printers/${printerId}/cost-policy`,
      changes,
    )
  },

  /**
   * One printed item's operational figures, each with its provenance.
   *
   * Readable by every role, including a viewer: visibility of a cost is never
   * restricted, only editing is (FR-007c).
   */
  getModelCostProfile: async (modelId: string): Promise<ModelCostProfile> => {
    return apiClient.get<ModelCostProfile>(`/api/v1/models/${modelId}/cost-profile`)
  },

  /**
   * Record a printed item's operational figures. Any member may.
   *
   * Fields left out are not touched, so entering the finishing time next week
   * does not erase the purge weight measured today. Each field that moves has
   * its origin written as `measured`, dated, against whoever entered it
   * (FR-001). A figure the engine currently reads as `observed` comes back as
   * a 409 rather than being typed over (FR-004).
   */
  updateModelCostProfile: async (
    modelId: string,
    changes: ModelCostProfileUpdate,
  ): Promise<ModelCostProfile> => {
    return apiClient.put<ModelCostProfile>(
      `/api/v1/models/${modelId}/cost-profile`,
      changes,
    )
  },

  /**
   * The price that achieves a target margin on one channel (FR-032).
   *
   * A `POST` because the body carries the target, not because anything
   * changes: the endpoint writes nothing and the answer is a proposal.
   *
   * A target no price can achieve comes back as a 422 whose `detail` is a
   * `PriceSolveResult` with `reason: "unachievable"` (FR-035). `solvePrice`
   * lets that reject, so a caller cannot read an unachievable answer as a
   * price by forgetting to check a flag; `trySolvePrice` below returns it as
   * data for the panel that wants to render the constraint.
   */
  solvePrice: async (
    productId: string,
    channelId: string,
    request: PriceSolveRequest,
  ): Promise<PriceSolveResult> => {
    return apiClient.post<PriceSolveResult>(
      `/api/v1/products/${productId}/pricing/${channelId}/solve`,
      request,
    )
  },

  /**
   * The same solve, with an unachievable target returned rather than thrown.
   *
   * FR-035 requires the binding constraint to reach the operator, and a
   * rejected promise carrying it inside an error body is awkward to render.
   * Anything that is not the solver's own 422 still rejects: a 404 or a 500 is
   * not an unachievable target and must not be shown as one.
   */
  trySolvePrice: async (
    productId: string,
    channelId: string,
    request: PriceSolveRequest,
  ): Promise<PriceSolveResult> => {
    try {
      return await pricingApi.solvePrice(productId, channelId, request)
    } catch (error) {
      const detail = (error as { response?: { status?: number; data?: { detail?: unknown } } })
        ?.response
      const body = detail?.data?.detail as PriceSolveResult | undefined
      if (detail?.status === 422 && body && body.reason === 'unachievable') {
        return body
      }
      throw error
    }
  },

  /**
   * Margin at each of a range of prices (FR-007).
   *
   * The range is required, deliberately: a default range's midpoint would
   * function as a recommended price while resting on nothing.
   */
  getPriceLadder: async (
    productId: string,
    channelId: string,
    params: PriceLadderParams,
  ): Promise<PriceLadder> => {
    const query = new URLSearchParams({
      price_from: params.price_from,
      price_to: params.price_to,
      step: params.step,
    })
    if (params.quantity !== undefined) query.append('quantity', params.quantity.toString())
    if (params.shipping_revenue !== undefined)
      query.append('shipping_revenue', params.shipping_revenue)
    if (params.as_of) query.append('as_of', params.as_of)

    return apiClient.get<PriceLadder>(
      `/api/v1/products/${productId}/pricing/${channelId}/ladder?${query.toString()}`,
    )
  },

  listFilamentPurchases: async (params?: {
    skip?: number
    limit?: number
  }): Promise<FilamentPurchaseListResponse> => {
    const query = new URLSearchParams()
    if (params?.skip !== undefined) query.append('skip', params.skip.toString())
    if (params?.limit !== undefined) query.append('limit', params.limit.toString())
    const queryString = query.toString()
    return apiClient.get<FilamentPurchaseListResponse>(
      `/api/v1/filament-purchases${queryString ? `?${queryString}` : ''}`,
    )
  },

  getFilamentPurchase: async (purchaseId: string): Promise<FilamentPurchase> => {
    return apiClient.get<FilamentPurchase>(`/api/v1/filament-purchases/${purchaseId}`)
  },

  createFilamentPurchase: async (data: FilamentPurchaseCreate): Promise<FilamentPurchase> => {
    return apiClient.post<FilamentPurchase>('/api/v1/filament-purchases', data)
  },

  updateFilamentPurchase: async (
    purchaseId: string,
    data: FilamentPurchaseUpdate,
  ): Promise<FilamentPurchase> => {
    return apiClient.put<FilamentPurchase>(`/api/v1/filament-purchases/${purchaseId}`, data)
  },

  deleteFilamentPurchase: async (purchaseId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/filament-purchases/${purchaseId}`)
  },
}

// ---------------------------------------------------------------------------
// Provenance and estimate proposals (User Story 6)
// ---------------------------------------------------------------------------

/**
 * Every recorded origin for one entity's numeric fields.
 *
 * Open to every role including a viewer (FR-007c): a margin cannot be judged
 * without seeing which of the figures behind it are measured and which are
 * guesses.
 */
export async function getProvenance(
  entityType: string,
  entityId: string,
): Promise<EntityProvenance> {
  const query = new URLSearchParams({ entity_type: entityType, entity_id: entityId })
  return apiClient.get<EntityProvenance>(`/api/v1/provenance?${query.toString()}`)
}

/**
 * Record where one figure came from.
 *
 * Refused with a 409 for a field whose current origin is `observed`, which is
 * read-only and refreshed only from its source (FR-004). Callers should read
 * `editable` from the field first rather than offering an edit that will fail.
 */
export async function putProvenance(
  entityType: string,
  entityId: string,
  fieldName: string,
  data: ProvenanceWriteRequest,
): Promise<FieldOrigin> {
  return apiClient.put<FieldOrigin>(
    `/api/v1/provenance/${entityType}/${entityId}/${fieldName}`,
    data,
  )
}

/** Proposals for this tenant, newest first. Defaults to the pending ones. */
export async function listEstimateRevisions(params?: {
  state?: RevisionState | null
  entityType?: string
  entityId?: string
}): Promise<EstimateRevisionList> {
  const query = new URLSearchParams()
  if (params?.state !== undefined && params.state !== null) query.set('state', params.state)
  if (params?.entityType) query.set('entity_type', params.entityType)
  if (params?.entityId) query.set('entity_id', params.entityId)
  const queryString = query.toString()
  return apiClient.get<EstimateRevisionList>(
    `/api/v1/estimate-revisions${queryString ? `?${queryString}` : ''}`,
  )
}

/**
 * Apply a held proposal, whole (FR-042c).
 *
 * There is no partial acceptance: a proposal is a single claim — "these
 * outcomes say the figure is this" — and accepting half of it would produce a
 * figure no evidence supports.
 */
export async function acceptEstimateRevision(revisionId: string): Promise<EstimateRevision> {
  return apiClient.post<EstimateRevision>(`/api/v1/estimate-revisions/${revisionId}/accept`, {})
}

/**
 * Decline a held proposal, leaving the estimate untouched.
 *
 * Not a permanent veto on the field: the outcomes behind it stay on record, so
 * the same question is not asked again but a new outcome can still raise it
 * (FR-042d).
 */
export async function rejectEstimateRevision(revisionId: string): Promise<EstimateRevision> {
  return apiClient.post<EstimateRevision>(`/api/v1/estimate-revisions/${revisionId}/reject`, {})
}

// ---------------------------------------------------------------------------
// Catalogue-wide scenarios (US7, FR-044)
// ---------------------------------------------------------------------------

/**
 * Request a shock across the catalogue.
 *
 * Returns immediately with a handle whose `state` is `queued` and whose
 * `result` is null (FR-044a). The work happens on a worker; poll
 * `getScenario` for the answer.
 */
export async function requestScenario(payload: ScenarioRunRequest): Promise<ScenarioRun> {
  return apiClient.post<ScenarioRun>('/api/v1/scenarios', payload)
}

/** One run's state and, once it has finished, its result. */
export async function getScenario(runId: string): Promise<ScenarioRun> {
  return apiClient.get<ScenarioRun>(`/api/v1/scenarios/${runId}`)
}

/** This tenant's scenario history, newest first. */
export async function listScenarios(params?: {
  limit?: number
  offset?: number
}): Promise<ScenarioRunList> {
  const query = new URLSearchParams()
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  const queryString = query.toString()
  return apiClient.get<ScenarioRunList>(
    `/api/v1/scenarios${queryString ? `?${queryString}` : ''}`,
  )
}
