/**
 * A model's test prints (spec 009, US4; SC-005).
 *
 * Headed by the line an operator needs before printing for real: how many
 * failure findings are still open, and how the last test went on which
 * version. Lists results newest first, filtered by outcome or version, each
 * with its measurements, failure mode and photo (private, loaded with the
 * session). Members record and correct.
 */
import { useState } from 'react'

import { AuthImage } from '@/components/ideas/AuthImage'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useFileNotes } from '@/hooks/useModelFileNotes'
import { useFileVersions } from '@/hooks/useModelFileVersions'
import { usePrintTestResults, useUpdateTestResult } from '@/hooks/usePreflight'
import { printTestResultsApi } from '@/lib/api/preflight'
import { apiErrorDetail } from '@/lib/apiError'
import { TEST_OUTCOMES, type PrintTestResult, type TestOutcome } from '@/types/preflight'
import { OUTCOME_CLASS, OUTCOME_TEXT, TEST_KIND_TEXT, preflightErrorText, valueText } from './preflightText'
import { RecordTestResultDialog } from './RecordTestResultDialog'

interface TestResultsPanelProps {
  modelId: string
  canWrite: boolean
}

export function SummaryLine({
  openFailures,
  latest,
}: {
  openFailures: number
  latest: PrintTestResult | undefined
}) {
  return (
    <span role="status" className="block text-sm">
      <span className={openFailures > 0 ? 'font-semibold text-red-700 dark:text-red-300' : ''}>
        {openFailures === 0 ? 'No open failure' : `${openFailures} open failure${openFailures > 1 ? 's' : ''}`}
      </span>
      {' · '}
      {latest ? (
        <>
          Last test: <strong>{OUTCOME_TEXT[latest.outcome]}</strong> ({TEST_KIND_TEXT[latest.kind]}
          {latest.version_label ? `, version ${latest.version_label}` : ''},{' '}
          {new Date(latest.created_at).toLocaleDateString()})
        </>
      ) : (
        'No test print recorded yet'
      )}
    </span>
  )
}

function ResultItem({ result, canWrite }: { result: PrintTestResult; canWrite: boolean }) {
  const update = useUpdateTestResult()
  const photo = printTestResultsApi.photoPath(result, 'thumb')
  return (
    <li className="flex gap-3 rounded-md border p-2 text-sm">
      {photo && <AuthImage path={photo} alt={`Photo of the ${TEST_KIND_TEXT[result.kind].toLowerCase()} test`} className="h-20 w-20 shrink-0 rounded object-cover" />}
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className={OUTCOME_CLASS[result.outcome]}>
            {OUTCOME_TEXT[result.outcome]}
          </Badge>
          <span className="font-medium">{TEST_KIND_TEXT[result.kind]}</span>
          {result.version_label && <span className="text-xs text-muted-foreground">version {result.version_label}</span>}
          {result.material_code && <span className="text-xs text-muted-foreground">{result.material_code}</span>}
          {result.orientation && <span className="text-xs text-muted-foreground">{result.orientation}</span>}
        </div>
        {result.failure_mode && <p className="break-words">Failure: {result.failure_mode}</p>}
        {result.measurements.length > 0 && (
          <ul className="text-xs text-muted-foreground">
            {result.measurements.map((m, index) => (
              <li key={index}>
                {m.name ?? `#${index + 1}`}: {valueText(m.value)}
                {m.unit ? ` ${m.unit}` : ''}
                {m.expected !== undefined ? ` (expected ${valueText(m.expected)})` : ''}
              </li>
            ))}
          </ul>
        )}
        {result.notes && <p className="whitespace-pre-wrap break-words text-xs">{result.notes}</p>}
        <p className="text-xs text-muted-foreground">
          {result.recorded_by?.name ?? 'Unknown'} · {new Date(result.created_at).toLocaleString()}
        </p>
        {canWrite && (
          <label className="flex items-center gap-2 text-xs">
            Correct outcome
            <select
              aria-label="Correct outcome"
              className="h-7 rounded border bg-background px-1 text-xs"
              value={result.outcome}
              disabled={update.isPending}
              onChange={(e) => update.mutate({ resultId: result.id, outcome: e.target.value as TestOutcome })}
            >
              {TEST_OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {OUTCOME_TEXT[o]}
                </option>
              ))}
            </select>
          </label>
        )}
        {update.error && <p className="text-xs text-destructive">{preflightErrorText(update.error)}</p>}
      </div>
    </li>
  )
}

export function TestResultsPanel({ modelId, canWrite }: TestResultsPanelProps) {
  const [outcome, setOutcome] = useState<TestOutcome | ''>('')
  const [versionId, setVersionId] = useState('')
  const [recording, setRecording] = useState(false)
  const { versions } = useFileVersions(modelId)
  const { results: latest } = usePrintTestResults({ model_id: modelId, limit: 1 })
  const { results, total, isLoading, error } = usePrintTestResults({
    model_id: modelId,
    ...(outcome ? { outcome } : {}),
    ...(versionId ? { model_file_version_id: versionId } : {}),
  })
  const { notes: failures } = useFileNotes(modelId, { severity: 'failure', status: 'open' })

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div className="space-y-1">
          <CardTitle>Test prints</CardTitle>
          <CardDescription>
            <SummaryLine openFailures={failures.length} latest={latest[0]} />
          </CardDescription>
        </div>
        {canWrite && (
          <Button size="sm" onClick={() => setRecording(true)}>
            Record a test
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Filter by outcome"
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as TestOutcome | '')}
          >
            <option value="">Any outcome</option>
            {TEST_OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {OUTCOME_TEXT[o]}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter by version"
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            <option value="">Any version</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorDetail(error)}
          </p>
        ) : isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No test results{outcome || versionId ? ' match' : ' yet'}.</p>
        ) : (
          <>
            <ul className="space-y-2">
              {results.map((result) => (
                <ResultItem key={result.id} result={result} canWrite={canWrite} />
              ))}
            </ul>
            {total > results.length && (
              <p className="text-xs text-muted-foreground">
                Showing {results.length} of {total}.
              </p>
            )}
          </>
        )}
      </CardContent>
      {canWrite && <RecordTestResultDialog modelId={modelId} open={recording} onOpenChange={setRecording} />}
    </Card>
  )
}
