/**
 * How a figure's origin is worded, and when a measurement has gone stale.
 *
 * Not a component module on purpose. Three screens label a figure's origin —
 * the cost breakdown, the provenance list and the proposal list — and they must
 * agree about what the labels mean: a figure called "Assumed" on one screen and
 * "Estimated" on another reads as two different things (Constitution III). The
 * wording lives here once, and `ProvenanceBadge` renders it.
 *
 * ## What the wording is doing
 *
 * - **Observed** and **Measured** both rest on evidence, so both read as
 *   positive. The difference is who took the reading, which the explanation
 *   says.
 * - **Your setting** rather than "Policy": the operator decided it, and
 *   "policy" sounds like something the software imposed on them.
 * - **Assumed** reads as a warning, because it is the honest answer and the one
 *   FR-001 wants visible. A default nobody chose is the figure most likely to
 *   be wrong.
 */

import type { CostLine, ProvenanceSource } from '@/types/pricing'

/** Human wording for each origin. One definition, used by every panel. */
export const SOURCE_LABEL: Record<ProvenanceSource, string> = {
  observed: 'Observed',
  measured: 'Measured',
  policy: 'Your setting',
  assumed: 'Assumed',
}

/** How much weight each origin carries, as the badge's colour. */
export const SOURCE_VARIANT: Record<ProvenanceSource, 'success' | 'secondary' | 'warning'> = {
  observed: 'success',
  measured: 'success',
  policy: 'secondary',
  assumed: 'warning',
}

/** What each origin means, for the title attribute. */
export const SOURCE_EXPLANATION: Record<ProvenanceSource, string> = {
  observed: 'Derived from recorded outcomes and refreshed from them automatically',
  measured: 'Measured by hand and recorded on the date shown',
  policy: 'A figure you set yourself; nothing updates it automatically',
  assumed: 'Nobody has measured or set this — it is a default, and may be wrong',
}

/**
 * Whether a hand measurement is past the operator's threshold (FR-005).
 *
 * Only `measured` figures go stale. A decision does not expire and an observed
 * figure is refreshed from its source, so flagging either would be noise that
 * trains the reader to ignore the flag.
 *
 * The comparison happens on this side because the threshold is a tenant
 * setting the caller already holds, and a `YYYY-MM-DD` difference in whole days
 * needs no timezone reasoning: the date is parsed as UTC midnight, so the
 * subtraction is exact.
 *
 * A missing or unparseable date is **not** stale. "Nobody has recorded this" is
 * a different fact, carried by the origin itself, and reporting it as stale
 * would tell the operator to re-measure something they never measured.
 */
export function isStaleMeasurement(
  line: Pick<CostLine, 'source' | 'as_of'>,
  thresholdDays: number | null | undefined,
): boolean {
  if (line.source !== 'measured' || !line.as_of || !thresholdDays) return false
  const measured = Date.parse(`${line.as_of}T00:00:00Z`)
  if (Number.isNaN(measured)) return false
  const days = Math.floor((Date.now() - measured) / 86_400_000)
  return days > thresholdDays
}
