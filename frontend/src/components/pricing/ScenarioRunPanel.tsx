/**
 * ScenarioRunPanel — ask the catalogue a question, and read the answer later.
 *
 * "If filament rose 25%, which of my products stop paying?" is a question
 * about two hundred products, so the request returns a handle and the work
 * happens on a worker (FR-044a). That makes the job's **state** part of the
 * interface rather than an implementation detail.
 *
 * ## What this screen must not do
 *
 * - **Appear to hang.** Every state is rendered, including `partial` and
 *   `failed`, and a failure shows its reason (FR-044b). A spinner that spins
 *   for ever is the one outcome worse than an error.
 * - **Let an old result read as current.** A finished run states the shock and
 *   the inputs it ran against, beside the time it finished (FR-044c). A
 *   fortnight later the material price may have moved twice, and a list of
 *   products with no stated question attached is indistinguishable from a
 *   report on today's figures.
 * - **Imply anything was changed.** A scenario writes no cost, price or
 *   provenance figure (FR-044d), and the panel says so where an operator is
 *   deciding whether to run one.
 *
 * ## Why the result is a list of names
 *
 * "14 products fall below 20%" sends an operator hunting. The products
 * themselves, with the margin each would report, is the answer they can act
 * on — so the below-floor list is the body of the result and the count is a
 * label on it.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Loader2, Play, XCircle } from 'lucide-react'

import { getScenario, listScenarios, requestScenario } from '@/lib/api/pricing'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { ScenarioRun, ScenarioState } from '@/types/pricing'

export interface ScenarioRunPanelProps {
  /** Pre-select one channel; omitted, every listed channel is swept. */
  salesChannelId?: string
  className?: string
}

/** How long a running job waits between polls. */
const POLL_MS = 3000

/** What each state is called, and what it means for the figures on screen. */
const STATE_LABEL: Record<ScenarioState, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Finished',
  partial: 'Finished with gaps',
  failed: 'Stopped',
}

const STATE_VARIANT: Record<ScenarioState, 'secondary' | 'success' | 'warning' | 'destructive'> = {
  queued: 'secondary',
  running: 'secondary',
  succeeded: 'success',
  partial: 'warning',
  failed: 'destructive',
}

const STATE_EXPLANATION: Record<ScenarioState, string> = {
  queued: 'Accepted and waiting for a worker. Nothing has been calculated yet.',
  running: 'Working through the catalogue. Larger catalogues take longer.',
  succeeded: 'Every listed product was costed under the shock.',
  partial: 'Some products could not be costed; they are listed with the reason.',
  failed: 'The run stopped before finishing. No figure was changed.',
}

function isTerminal(state: ScenarioState): boolean {
  return state === 'succeeded' || state === 'partial' || state === 'failed'
}

function StateIcon({ state }: { state: ScenarioState }) {
  if (state === 'running' || state === 'queued') {
    return <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
  }
  if (state === 'failed') return <XCircle className="h-4 w-4" aria-hidden="true" />
  if (state === 'partial') return <AlertTriangle className="h-4 w-4" aria-hidden="true" />
  return <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
}

/** A percentage as a reader judges it, from the decimal string the API sent. */
function pct(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const parsed = Number.parseFloat(value)
  return Number.isNaN(parsed) ? value : `${parsed.toFixed(1)}%`
}

/** A money amount, kept as the string it arrived as. */
function money(value: string | null | undefined): string {
  return value === null || value === undefined ? '—' : value
}

function shockSummary(shock: Record<string, string>): string {
  const moved = Object.entries(shock)
    .filter(([, value]) => Number.parseFloat(value) !== 0)
    .map(([key, value]) => `${key.replace(/_pct$/, '').replace(/_/g, ' ')} ${pct(value)}`)
  return moved.length > 0 ? moved.join(', ') : 'no change'
}

function RunState({ run }: { run: ScenarioRun }) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`scenario-state-${run.state}`}>
      <Badge variant={STATE_VARIANT[run.state]} className="gap-1" title={STATE_EXPLANATION[run.state]}>
        <StateIcon state={run.state} />
        {STATE_LABEL[run.state]}
      </Badge>
      {run.finished_at && (
        <span className="text-xs text-muted-foreground">finished {run.finished_at}</span>
      )}
    </div>
  )
}

/**
 * What the run was asking, beside what it found.
 *
 * Always rendered for a finished run, never collapsed behind a disclosure:
 * FR-044c exists because a result without its question attached is read as a
 * report on current figures.
 */
function RunProvenance({ run }: { run: ScenarioRun }) {
  const inputs = run.result?.inputs ?? run.inputs ?? {}
  return (
    <div className="space-y-1 rounded-md bg-muted/50 p-3 text-xs" data-testid="scenario-inputs">
      <div>
        <span className="text-muted-foreground">Shock: </span>
        <span className="font-medium">{shockSummary(run.result?.shock ?? run.shock)}</span>
      </div>
      <div>
        <span className="text-muted-foreground">Margin floor: </span>
        <span className="font-medium">{pct(run.margin_floor_pct)}</span>
      </div>
      {Object.entries(inputs)
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .map(([key, value]) => (
          <div key={key}>
            <span className="text-muted-foreground">{key.replace(/_/g, ' ')}: </span>
            <span className="font-medium">{String(value)}</span>
          </div>
        ))}
      <p className="pt-1 text-muted-foreground">
        These are the figures the run used, not today's. Nothing was changed by it.
      </p>
    </div>
  )
}

function BelowFloorTable({ run }: { run: ScenarioRun }) {
  const rows = run.result?.below_floor ?? []

  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="scenario-none-below-floor">
        Every product the sweep costed stays above your floor under this shock.
      </p>
    )
  }

  return (
    <Table data-testid="scenario-below-floor">
      <TableHeader>
        <TableRow>
          <TableHead>Product</TableHead>
          <TableHead>Channel</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead className="text-right">Make cost</TableHead>
          <TableHead className="text-right">Margin</TableHead>
          <TableHead className="text-right">Per machine-hour</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((entry) => (
          <TableRow key={`${entry.product_id}:${entry.sales_channel_id}`}>
            <TableCell>
              <div className="font-medium">{entry.name}</div>
              <div className="text-xs text-muted-foreground">{entry.sku}</div>
            </TableCell>
            <TableCell className="text-sm">{entry.channel_name}</TableCell>
            <TableCell className="text-right tabular-nums">{money(entry.list_price)}</TableCell>
            <TableCell className="text-right tabular-nums">{money(entry.make_cost)}</TableCell>
            <TableCell className="text-right tabular-nums">
              {/* Null means undefined, not zero: fees consumed the whole
                  basis. Rendering 0% would read as break-even. */}
              {entry.margin_pct === null ? (
                <span title="Fees consume the whole basis, so a margin cannot be stated">
                  undefined
                </span>
              ) : (
                pct(entry.margin_pct)
              )}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {entry.profit_per_machine_hour === null ? (
                <span title="Nobody has recorded how long this takes to print">—</span>
              ) : (
                money(entry.profit_per_machine_hour)
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function SkippedList({ run }: { run: ScenarioRun }) {
  const skipped = run.result?.skipped ?? []
  if (skipped.length === 0) return null

  return (
    <div className="space-y-1 rounded-md border border-yellow-500/40 p-3" data-testid="scenario-skipped">
      <p className="text-sm font-medium">
        {skipped.length} product{skipped.length === 1 ? '' : 's'} could not be costed
      </p>
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
        {skipped.map((entry) => (
          <li key={`${entry.product_id}:${entry.sales_channel_id}`}>
            <span className="font-mono">{entry.sku}</span> — {entry.reason}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ScenarioRunPanel({ salesChannelId, className }: ScenarioRunPanelProps) {
  const queryClient = useQueryClient()
  const [materialPct, setMaterialPct] = useState('25')
  const [floorPct, setFloorPct] = useState('20')
  const [watching, setWatching] = useState<string | null>(null)

  const history = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => listScenarios({ limit: 10 }),
  })

  const watched = useQuery({
    queryKey: ['scenario', watching],
    queryFn: () => getScenario(watching as string),
    enabled: watching !== null,
    // Polled only while the job is unfinished. A terminal run is final: there
    // is nothing further to learn and the result must not change under a
    // reader (FR-038's habit applied to a hypothetical).
    refetchInterval: (query) => {
      const run = query.state.data
      return run && isTerminal(run.state) ? false : POLL_MS
    },
  })

  const request = useMutation({
    mutationFn: () =>
      requestScenario({
        shock: { material_cost_pct: materialPct },
        margin_floor_pct: floorPct,
        sales_channel_id: salesChannelId,
      }),
    onSuccess: (run) => {
      setWatching(run.id)
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
    },
  })

  const run = watched.data ?? null

  return (
    <Card className={className} data-testid="scenario-panel">
      <CardHeader>
        <CardTitle>What would a price rise do?</CardTitle>
        <CardDescription>
          Applies a shock across every listed product and reports the ones that fall below your
          floor. Nothing is changed — no cost, price or origin is written.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="scenario-material">Material cost change</Label>
            <Input
              id="scenario-material"
              value={materialPct}
              onChange={(event) => setMaterialPct(event.target.value)}
              className="w-28 tabular-nums"
              inputMode="decimal"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="scenario-floor">Margin floor</Label>
            <Input
              id="scenario-floor"
              value={floorPct}
              onChange={(event) => setFloorPct(event.target.value)}
              className="w-28 tabular-nums"
              inputMode="decimal"
            />
          </div>
          <Button onClick={() => request.mutate()} disabled={request.isPending}>
            {request.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            Run the scenario
          </Button>
        </div>

        {request.isError && (
          <p className="text-sm text-destructive" role="alert" data-testid="scenario-request-error">
            That scenario could not be queued. Nothing was changed — check the figures and try
            again.
          </p>
        )}

        {run && (
          <div className="space-y-3 rounded-md border p-3" data-testid="scenario-run">
            <RunState run={run} />

            {run.state === 'queued' && (
              <p className="text-sm text-muted-foreground">
                Accepted. Nothing has been calculated yet — this page will update itself.
              </p>
            )}

            {run.state === 'running' && (
              <p className="text-sm text-muted-foreground">
                Working through the catalogue. A larger catalogue takes longer; it does not fail.
              </p>
            )}

            {run.state === 'failed' && (
              <p className="text-sm text-destructive" role="alert" data-testid="scenario-error">
                {run.error_text ?? 'The run stopped without recording a reason.'}
              </p>
            )}

            {isTerminal(run.state) && run.state !== 'failed' && (
              <>
                <p className="text-sm">
                  <span className="font-medium" data-testid="scenario-evaluated">
                    {run.result?.evaluated ?? 0}
                  </span>{' '}
                  product{(run.result?.evaluated ?? 0) === 1 ? '' : 's'} costed,{' '}
                  <span className="font-medium" data-testid="scenario-below-count">
                    {run.result?.below_floor.length ?? 0}
                  </span>{' '}
                  below your floor.
                </p>
                <SkippedList run={run} />
                <BelowFloorTable run={run} />
              </>
            )}

            <RunProvenance run={run} />
          </div>
        )}

        {history.data && history.data.runs.length > 0 && (
          <div className="space-y-1" data-testid="scenario-history">
            <p className="text-sm font-medium">Earlier scenarios</p>
            <ul className="space-y-1 text-xs">
              {history.data.runs.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    className="text-left underline-offset-2 hover:underline"
                    onClick={() => setWatching(entry.id)}
                  >
                    {shockSummary(entry.shock)} · floor {pct(entry.margin_floor_pct)} ·{' '}
                    {STATE_LABEL[entry.state]}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
