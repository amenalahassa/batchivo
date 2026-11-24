/**
 * PrinterSendsDialog — recent sends of a printer and their spool deduction (spec 011, US4).
 *
 * When a print sent from Batchivo ends, it proposes deducting from each spool
 * the grams the sliced file expected. Nothing moves until the operator accepts
 * — possibly after correcting an amount — or dismisses the proposal.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAcceptConsumption, useDismissConsumption, usePrintSends } from '@/hooks/usePrintSends'
import { printSendErrorMessage } from '@/lib/api/printSends'
import { spoolsApi } from '@/lib/api/spools'
import type { PrintSend } from '@/types/printSend'
import type { SpoolResponse } from '@/types/spool'

const STATUS_LABELS: Record<string, string> = {
  prepared: 'Prepared (not sent)',
  confirming: 'Sending…',
  started: 'Sent',
  transfer_failed: 'Transfer failed',
  start_failed: 'Start failed',
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

const SPOOL_PAGE_SIZE = 100

/** Every active spool of the shop, page by page (the list API caps a page at 100). */
async function listActiveSpools(): Promise<SpoolResponse[]> {
  const spools: SpoolResponse[] = []
  for (let page = 1; ; page += 1) {
    const result = await spoolsApi.list({ is_active: true, page, page_size: SPOOL_PAGE_SIZE })
    spools.push(...result.spools)
    if (result.spools.length < SPOOL_PAGE_SIZE || spools.length >= result.total) return spools
  }
}

function ConsumptionProposal({ printerId, send }: { printerId: string; send: PrintSend }) {
  const accept = useAcceptConsumption(printerId)
  const dismiss = useDismissConsumption(printerId)
  // Any active spool can be picked for a line, including one with no spool recorded
  // (external spool holder, unknown slot) — US4/AC5.
  const { data: activeSpools = [] } = useQuery({
    queryKey: ['spools', 'active-for-deduction'],
    queryFn: listActiveSpools,
  })
  const [spoolChoice, setSpoolChoice] = useState<Record<number, string>>(() =>
    Object.fromEntries(send.consumption.lines.map((l) => [l.filament_id, l.spool_id ?? '']))
  )
  const [grams, setGrams] = useState<Record<number, string>>(() =>
    Object.fromEntries(send.consumption.lines.map((l) => [l.filament_id, l.proposed_grams]))
  )
  const [included, setIncluded] = useState<Record<number, boolean>>(() =>
    Object.fromEntries(send.consumption.lines.map((l) => [l.filament_id, l.spool_id != null]))
  )

  const lines = send.consumption.lines
    .filter((l) => included[l.filament_id] && spoolChoice[l.filament_id])
    .map((l) => ({
      filament_id: l.filament_id,
      spool_id: spoolChoice[l.filament_id],
      grams: (grams[l.filament_id] ?? '').trim(),
    }))
  const valid = lines.length > 0 && lines.every((l) => Number(l.grams) > 0)

  return (
    <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50/50 p-3">
      <p className="text-sm font-medium">Deduct the filament this print used?</p>
      {send.consumption.lines.map((line) => {
        const chosen = spoolChoice[line.filament_id] ?? ''
        const mapped = send.lines.find((l) => l.filament_id === line.filament_id)?.mapped_spool
        const options = activeSpools.map((spool) => ({
          id: spool.id,
          label: `${spool.spool_id} · ${spool.filament_type?.material_type_code ?? '?'} ${
            spool.filament_type?.color ?? ''
          }`.trim(),
        }))
        if (mapped && !options.some((o) => o.id === mapped.id)) {
          options.unshift({
            id: mapped.id,
            label: `${mapped.spool_id} · ${mapped.material ?? '?'}`,
          })
        }
        return (
          <div key={line.filament_id} className="flex flex-wrap items-center gap-2 text-sm">
            <input
              type="checkbox"
              aria-label={`Deduct filament ${line.filament_id}`}
              checked={Boolean(included[line.filament_id])}
              disabled={!chosen}
              onChange={(e) =>
                setIncluded((current) => ({
                  ...current,
                  [line.filament_id]: e.target.checked,
                }))
              }
            />
            <span>Filament {line.filament_id}</span>
            <select
              aria-label={`Spool for filament ${line.filament_id}`}
              className="h-8 max-w-[14rem] rounded-md border bg-background px-2"
              value={chosen}
              onChange={(e) => {
                const value = e.target.value
                setSpoolChoice((current) => ({
                  ...current,
                  [line.filament_id]: value,
                }))
                setIncluded((current) => ({
                  ...current,
                  [line.filament_id]: value !== '',
                }))
              }}
            >
              <option value="">No spool — leave out</option>
              {options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
            <Label htmlFor={`grams-${send.id}-${line.filament_id}`} className="sr-only">
              Grams for filament {line.filament_id}
            </Label>
            <Input
              id={`grams-${send.id}-${line.filament_id}`}
              className="h-8 w-24"
              inputMode="decimal"
              value={grams[line.filament_id] ?? ''}
              disabled={!chosen}
              onChange={(e) =>
                setGrams((current) => ({
                  ...current,
                  [line.filament_id]: e.target.value,
                }))
              }
            />
            <span className="text-muted-foreground">g (expected {line.proposed_grams} g)</span>
          </div>
        )
      })}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={!valid || accept.isPending}
          onClick={() => accept.mutate({ sendId: send.id, lines })}
        >
          {accept.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Accept deduction
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={dismiss.isPending}
          onClick={() => dismiss.mutate(send.id)}
        >
          Dismiss
        </Button>
      </div>
      {(accept.error || dismiss.error) && (
        <p className="text-sm text-destructive" role="alert">
          {printSendErrorMessage(accept.error ?? dismiss.error)}
        </p>
      )}
    </div>
  )
}

interface PrinterSendsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  printerId: string
  printerName: string
}

export function PrinterSendsDialog({
  open,
  onOpenChange,
  printerId,
  printerName,
}: PrinterSendsDialogProps) {
  const { sends, isLoading } = usePrintSends(open ? printerId : null)
  const shown = sends.filter((s) => s.status !== 'prepared')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Sends — {printerName}</DialogTitle>
          <DialogDescription>Prints sent from Batchivo to this printer.</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No print has been sent to this printer yet.
          </p>
        ) : (
          <ul className="space-y-3">
            {shown.map((send) => (
              <li key={send.id} className="space-y-2 rounded-md border p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">
                    {send.file.name} · plate {send.plate.index}
                  </span>
                  <Badge variant="outline">
                    {send.print_job ? `Job ${send.print_job.status}` : STATUS_LABELS[send.status]}
                  </Badge>
                </div>
                <p className="text-muted-foreground">
                  Confirmed {when(send.confirmed_at)}
                  {send.confirmed_by && ` by ${send.confirmed_by.name}`}
                  {send.warnings_acknowledged && ' · warnings acknowledged'}
                  {send.print_job?.completed_at && ` · ended ${when(send.print_job.completed_at)}`}
                </p>
                <ul
                  className="text-muted-foreground"
                  aria-label={`Slot mapping of ${send.file.name}`}
                >
                  {send.lines.map((line) => (
                    <li key={line.filament_id}>
                      Filament {line.filament_id} ({line.expected.type ?? '?'}) → {line.slot.label}
                      {line.mapped_spool && ` · ${line.mapped_spool.spool_id}`}
                    </li>
                  ))}
                </ul>
                {send.error_message && <p className="text-destructive">{send.error_message}</p>}
                {send.consumption.status === 'pending' && (
                  <ConsumptionProposal printerId={printerId} send={send} />
                )}
                {send.consumption.status === 'accepted' && (
                  <p className="text-muted-foreground">
                    Deducted:{' '}
                    {send.consumption.lines
                      .filter((l) => l.accepted_grams)
                      .map((l) => `${l.accepted_grams} g (filament ${l.filament_id})`)
                      .join(', ')}
                  </p>
                )}
                {send.consumption.status === 'dismissed' && (
                  <p className="text-muted-foreground">Deduction dismissed.</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
