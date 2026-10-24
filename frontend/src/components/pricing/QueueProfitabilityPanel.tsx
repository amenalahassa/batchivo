/**
 * QueueProfitabilityPanel — the print queue ordered by what pays per
 * machine-hour (T234, FR-043, US7 acceptance scenario 1).
 *
 * `PrintQueueService.profitability_ranking` was the ranking US7 is named for
 * and nothing called it: no route served it and the console had no queue
 * screen. This reads it.
 *
 * - **Priority still comes first.** The operator's urgent job stays at the top;
 *   within a priority, what pays per machine-hour replaces arrival order.
 * - **It reorders nothing.** The ranking is advice beside the queue, open to
 *   every role, and moves no job.
 * - **No figure is not zero.** A job whose print nobody has timed, or whose
 *   product has no price on the channel, sorts last with the reason it has no
 *   figure: a zero would read as a job that earns nothing.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCurrency } from '@/hooks/useCurrency'
import { printQueueApi } from '@/lib/api/printQueue'
import { formatMoney, formatPercent } from '@/lib/money'
import type { PrintJobStatus } from '@/types/pricing'

const STATUSES: { value: PrintJobStatus; label: string }[] = [
  { value: 'pending', label: 'Pending' },
  { value: 'queued', label: 'Queued' },
]

export function QueueProfitabilityPanel() {
  const { currency } = useCurrency()
  const [status, setStatus] = useState<PrintJobStatus>('pending')
  const ranking = useQuery({
    queryKey: ['print-queue', 'profitability', status],
    queryFn: () => printQueueApi.profitability({ status }),
  })

  return (
    <Card data-testid="queue-profitability">
      <CardHeader>
        <CardTitle>Queue by profit per machine-hour</CardTitle>
        <CardDescription>
          Your priority still comes first; within it, the job that pays most for the machine time
          it takes is listed first. This reorders nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Label htmlFor="queue-status">Jobs</Label>
          <select
            id="queue-status"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={status}
            onChange={(event) => setStatus(event.target.value as PrintJobStatus)}
          >
            {STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {ranking.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Ranking the queue…
          </div>
        ) : ranking.isError ? (
          <p className="text-sm text-destructive" data-testid="queue-profitability-error">
            The ranking could not be loaded.
          </p>
        ) : !ranking.data || ranking.data.entries.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="queue-profitability-empty">
            No {status} jobs to rank.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[50px]">#</TableHead>
                <TableHead>Job</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead className="text-right">Per machine-hour</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">Machine hours</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ranking.data.entries.map((entry, index) => (
                <TableRow key={entry.job_id} data-testid={`queue-job-${entry.job_id}`}>
                  <TableCell className="tabular-nums">{index + 1}</TableCell>
                  <TableCell>
                    <div className="font-medium">
                      {entry.product_name ?? entry.model_name ?? 'Unnamed job'}
                    </div>
                    {entry.reason && (
                      <div className="text-xs text-muted-foreground" data-testid="queue-job-reason">
                        {entry.reason}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={entry.priority === 'urgent' ? 'destructive' : 'outline'}>
                      {entry.priority}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-medium">
                    {entry.profit_per_machine_hour == null
                      ? '—'
                      : formatMoney(entry.profit_per_machine_hour, currency.symbol)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatPercent(entry.margin_pct)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {entry.machine_hours ?? '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
