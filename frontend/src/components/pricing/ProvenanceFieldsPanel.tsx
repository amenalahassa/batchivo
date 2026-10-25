/**
 * ProvenanceFieldsPanel — every input behind a cost, with where it came from.
 *
 * The cost breakdown names each line's weakest origin. This lists the inputs
 * themselves: each figure's source, date, confidence and staleness, read from
 * `GET /provenance` (FR-001, US6/AC1).
 *
 * It is also where a stale hand measurement is re-confirmed. A measurement
 * past the threshold is flagged (FR-005); re-measuring and finding the same
 * figure should clear the flag without the operator having to change a value
 * that is still right. "Still correct" records the same source, dated today
 * (T259). An observed figure has no such button: it is refreshed only from its
 * source (FR-004).
 */

import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useEntityProvenance, useReconfirmProvenance } from '@/hooks/usePricing'
import { ProvenanceBadge } from './ProvenanceBadge'

export interface ProvenanceFieldsPanelProps {
  entityType: string
  entityId: string
}

/** Today as the API dates a figure: an ISO date. */
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function ProvenanceFieldsPanel({ entityType, entityId }: ProvenanceFieldsPanelProps) {
  const { provenance, isLoading, error } = useEntityProvenance(entityType, entityId)
  const { reconfirm, isSaving, error: saveError } = useReconfirmProvenance(entityType, entityId)

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Reading where these figures came from…
      </div>
    )
  }

  if (error || !provenance) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          {error instanceof Error ? error.message : 'The figures’ origins could not be read.'}
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-2" data-testid="provenance-fields">
      <p className="text-xs text-muted-foreground">
        {provenance.observed_count} of {provenance.total_count} figures observed
        {provenance.stale_count > 0
          ? `, ${provenance.stale_count} measured more than ${provenance.staleness_threshold_days} days ago`
          : ''}
        .
      </p>

      {saveError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{saveError.message}</AlertDescription>
        </Alert>
      )}

      <ul className="divide-y">
        {provenance.fields.map((field) => (
          <li
            key={field.field_name}
            className="flex flex-wrap items-center justify-between gap-2 py-1.5"
            data-testid={`provenance-field-${field.field_name}`}
          >
            <span className="text-sm">{field.description}</span>
            <span className="flex items-center gap-2">
              <ProvenanceBadge
                source={field.source}
                asOf={field.as_of}
                isStale={field.is_stale}
                isDefault={field.is_default}
                hasPendingRevision={field.has_pending_revision}
                confidence={field.confidence}
              />
              {field.source === 'measured' && field.editable && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={isSaving}
                  onClick={() =>
                    reconfirm({ fieldName: field.field_name, source: 'measured', asOf: today() })
                  }
                  title="Re-measured and found the same: dates the figure today without changing it"
                >
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  Still correct
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
