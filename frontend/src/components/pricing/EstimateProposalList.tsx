/**
 * EstimateProposalList — observations that disagree with an estimate.
 *
 * A proposal lands here when recorded outcomes diverge from the figure in use
 * by more than the operator's threshold (FR-042b). That threshold exists
 * because **a large disagreement is more often a faulty measurement than a
 * discovery** — a smart plug reporting kilowatts instead of watts, a print
 * logged at 95 hours instead of 9.5. So the figure does not move and a person
 * decides.
 *
 * ## What this screen must say, and why
 *
 * - **The estimate, the observation, and the gap** (FR-042c). All three, with
 *   the gap stated rather than left to be eyeballed: "100 → 910" is a fact,
 *   "810% out" is the judgement that makes it reviewable.
 * - **That pricing still uses the current figure** (FR-042e). Without that
 *   sentence a reader cannot tell whether they are approving a change or
 *   undoing one that already happened, and the two have opposite urgency.
 * - **Which outcomes it came from** (FR-042c). A reviewer who cannot see the
 *   readings is guessing, and the whole point of holding the proposal is to
 *   let a human look at them.
 * - **That rejecting is not a veto on the field** (FR-042d). Somebody who
 *   believes "reject" silences the figure for ever will accept a bad reading
 *   rather than lose the alert.
 *
 * ## Accepted or rejected whole
 *
 * There is no partial acceptance (FR-042c). A proposal is a single claim —
 * these outcomes say the figure is this — and taking half of it would produce
 * a figure no evidence supports.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Loader2, X } from 'lucide-react'

import {
  acceptEstimateRevision,
  listEstimateRevisions,
  rejectEstimateRevision,
} from '@/lib/api/pricing'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { formatShare } from '@/lib/money'
import type { EstimateRevision } from '@/types/pricing'

export interface EstimateProposalListProps {
  /** Narrow to one record's proposals. Omitted, every pending one is listed. */
  entityType?: string
  entityId?: string
  className?: string
}

/** `print_time_minutes` reads badly on a screen; "print time minutes" does not. */
function fieldLabel(fieldName: string): string {
  return fieldName.replace(/_/g, ' ')
}

/**
 * A divergence as a reader judges it.
 *
 * Rendered from the decimal string the API sent and trimmed to one place
 * (Constitution IV): `parseFloat` is used only for the display rounding, never
 * to carry the value, and the untrimmed string stays available in the title.
 */
function divergenceLabel(pct: string): string {
  const value = Number.parseFloat(pct)
  if (Number.isNaN(value)) return pct
  return `${value.toFixed(1)}%`
}

/** A figure trimmed of the trailing zeros its column's scale added. */
function trimValue(value: string): string {
  if (!value.includes('.')) return value
  return value.replace(/0+$/, '').replace(/\.$/, '')
}

function ProposalRow({
  revision,
  onAccept,
  onReject,
  busy,
}: {
  revision: EstimateRevision
  onAccept: (revision: EstimateRevision) => void
  onReject: (revision: EstimateRevision) => void
  busy: boolean
}) {
  const outcomes = revision.derived_from_run_ids

  return (
    <div
      className="space-y-2 rounded-md border p-3"
      data-testid={`proposal-${revision.id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium capitalize">{fieldLabel(revision.field_name)}</div>
          <div className="text-xs text-muted-foreground">
            {revision.entity_type} · observed up to {revision.observed_as_of}
          </div>
        </div>
        <Badge
          variant="outline"
          className="border-yellow-500/50 text-yellow-700 dark:text-yellow-500"
          title={`Exactly ${revision.divergence_pct}% when this was raised`}
          data-testid="proposal-divergence"
        >
          {divergenceLabel(revision.divergence_pct)} out
        </Badge>
      </div>

      {/* FR-042c: both values, and which is which. The arrow makes the
          direction unmistakable, which a two-column table does not. */}
      <div className="flex flex-wrap items-baseline gap-2 text-sm">
        <span className="text-muted-foreground">Now in use</span>
        <span className="tabular-nums font-medium" data-testid="proposal-current">
          {trimValue(revision.current_value)}
        </span>
        <span aria-hidden="true">→</span>
        <span className="text-muted-foreground">observed</span>
        <span className="tabular-nums font-medium" data-testid="proposal-observed">
          {trimValue(revision.observed_value)}
        </span>
      </div>

      {/* FR-042e. Without this a reader cannot tell whether they are approving
          a change or undoing one that already happened. */}
      <p className="text-xs text-muted-foreground">
        Pricing still uses {trimValue(revision.current_value)}. Nothing changes until you
        accept.
      </p>

      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">
          From {outcomes.length} recorded {outcomes.length === 1 ? 'outcome' : 'outcomes'}
          {/* How far the evidence goes (T259, US6/AC1): the count and agreement
              of the outcomes, so a reviewer weighs a thin proposal as one. */}
          {revision.confidence && (
            <span data-testid="proposal-confidence">
              {' '}
              · {formatShare(revision.confidence)} confidence
            </span>
          )}
        </summary>
        <ul className="mt-1 list-disc space-y-0.5 pl-5" data-testid="proposal-outcomes">
          {outcomes.map((runId) => (
            <li key={runId} className="font-mono">
              {runId}
            </li>
          ))}
        </ul>
      </details>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => onAccept(revision)}
          aria-label={`Accept the observed ${fieldLabel(revision.field_name)}`}
        >
          {busy ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Check className="mr-2 h-4 w-4" />
          )}
          Use the observed figure
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onReject(revision)}
          aria-label={`Reject the observed ${fieldLabel(revision.field_name)}`}
        >
          <X className="mr-2 h-4 w-4" />
          Keep the current figure
        </Button>
      </div>
    </div>
  )
}

export function EstimateProposalList({
  entityType,
  entityId,
  className,
}: EstimateProposalListProps) {
  const queryClient = useQueryClient()
  const [rejecting, setRejecting] = useState<EstimateRevision | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['estimate-revisions', { state: 'pending', entityType, entityId }],
    queryFn: () => listEstimateRevisions({ state: 'pending', entityType, entityId }),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['estimate-revisions'] })
    // Accepting moves a figure, so every cost read from it is now wrong.
    queryClient.invalidateQueries({ queryKey: ['provenance'] })
    queryClient.invalidateQueries({ queryKey: ['cost-breakdown'] })
  }

  const acceptMutation = useMutation({
    mutationFn: (revisionId: string) => acceptEstimateRevision(revisionId),
    onSuccess: invalidate,
  })

  const rejectMutation = useMutation({
    mutationFn: (revisionId: string) => rejectEstimateRevision(revisionId),
    onSuccess: () => {
      invalidate()
      setRejecting(null)
    },
  })

  const busy = acceptMutation.isPending || rejectMutation.isPending

  if (isLoading) {
    return (
      <Card className={className} data-testid="estimate-proposals-loading">
        <CardContent className="flex items-center gap-2 py-8 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Looking for observations that disagree…
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card className={className} data-testid="estimate-proposals-error">
        <CardContent className="py-8 text-sm text-muted-foreground" role="alert">
          The review list could not be loaded. Your figures are unchanged.
        </CardContent>
      </Card>
    )
  }

  const revisions = data?.revisions ?? []

  return (
    <Card className={className} data-testid="estimate-proposals">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <span>Observations awaiting review</span>
          {revisions.length > 0 && (
            <Badge variant="outline" data-testid="proposal-count">
              {revisions.length}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          {revisions.length === 0
            ? 'Nothing is waiting. Where recorded outcomes agree with an estimate, the figure updates on its own.'
            : 'These readings disagree with the figures in use by more than your threshold, which is usually a faulty measurement rather than a change. Nothing moves until you decide.'}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {revisions.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="no-proposals">
            No observation currently disagrees with an estimate.
          </p>
        ) : (
          revisions.map((revision) => (
            <ProposalRow
              key={revision.id}
              revision={revision}
              busy={busy}
              onAccept={(target) => acceptMutation.mutate(target.id)}
              onReject={(target) => setRejecting(target)}
            />
          ))
        )}

        {(acceptMutation.isError || rejectMutation.isError) && (
          <p className="text-sm text-destructive" role="alert" data-testid="proposal-error">
            That decision could not be recorded. The figure is unchanged — reload and try
            again.
          </p>
        )}
      </CardContent>

      {/* Rejecting is confirmed, because an operator who believes it silences
          the figure for ever would accept a bad reading rather than lose the
          alert. The wording says what FR-042d actually does. */}
      <AlertDialog
        open={rejecting !== null}
        onOpenChange={(open) => !open && setRejecting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              Keep the current figure?
            </AlertDialogTitle>
            <AlertDialogDescription>
              {rejecting && (
                <>
                  {fieldLabel(rejecting.field_name)} stays at{' '}
                  {trimValue(rejecting.current_value)}. These{' '}
                  {rejecting.derived_from_run_ids.length} readings will not be proposed again
                  — but a new recorded outcome can raise it afresh, so you are not switching
                  the alert off.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => rejecting && rejectMutation.mutate(rejecting.id)}
            >
              Keep the current figure
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
