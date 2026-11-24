/**
 * PrintSendSummary — what will be printed, and what is loaded where (spec 011, US1).
 *
 * The summary is what the operator confirms: printer, file, plate, estimated
 * time and weight, and for each filament of the plate the slot it is drawn
 * from, the spool Batchivo maps there and what the printer reports, with a
 * warning next to any mismatch.
 */

import { AlertTriangle, Ban } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { PrintSendSummary as Summary } from '@/types/printSend'

const WARNING_LABELS: Record<string, string> = {
  material_mismatch: 'Material differs',
  color_mismatch: 'Colour differs',
  empty_slot: 'Slot empty',
  unknown_spool: 'No spool recorded',
  reported_mismatch: 'Printer reports something else',
}

function formatMinutes(minutes: number | null): string {
  if (minutes == null) return '—'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h} h ${m.toString().padStart(2, '0')} min` : `${m} min`
}

function Swatch({ color }: { color: string | null }) {
  if (!color) return null
  return (
    <span
      className="inline-block h-3 w-3 rounded-full border align-middle"
      style={{ backgroundColor: color }}
      aria-hidden="true"
    />
  )
}

export function PrintSendSummary({ summary }: { summary: Summary }) {
  return (
    <div className="space-y-4" data-testid="print-send-summary">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <dt className="text-muted-foreground">Printer</dt>
        <dd className="font-medium">{summary.printer.name}</dd>
        <dt className="text-muted-foreground">File</dt>
        <dd className="truncate font-medium" title={summary.file.name}>
          {summary.file.name}
        </dd>
        <dt className="text-muted-foreground">Plate</dt>
        <dd className="font-medium">{summary.plate.index}</dd>
        <dt className="text-muted-foreground">Estimated time</dt>
        <dd className="font-medium">{formatMinutes(summary.plate.print_time_minutes)}</dd>
        <dt className="text-muted-foreground">Filament</dt>
        <dd className="font-medium">
          {summary.plate.filament_weight_grams ? `${summary.plate.filament_weight_grams} g` : '—'}
        </dd>
      </dl>

      <ul className="divide-y rounded-md border">
        {summary.lines.map((line) => (
          <li key={line.filament_id} className="space-y-1 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">Filament {line.filament_id}</span>
              <Swatch color={line.expected.color} />
              <span>{line.expected.type ?? 'Unknown material'}</span>
              {line.expected.grams && (
                <span className="text-muted-foreground">{line.expected.grams} g</span>
              )}
              <span className="text-muted-foreground">→ {line.slot.label}</span>
            </div>
            <div className="flex flex-wrap gap-x-4 text-muted-foreground">
              <span>
                Batchivo:{' '}
                {line.mapped_spool ? (
                  <>
                    <Swatch color={line.mapped_spool.color} /> {line.mapped_spool.material ?? '?'} (
                    {line.mapped_spool.spool_id})
                  </>
                ) : line.slot.kind === 'external' ? (
                  'external spool'
                ) : (
                  'no spool recorded'
                )}
              </span>
              {line.slot.kind === 'ams' && (
                <span>
                  Printer:{' '}
                  {line.reported == null
                    ? 'unknown'
                    : line.reported.present
                      ? `${line.reported.type ?? '?'}`
                      : 'empty'}
                </span>
              )}
            </div>
            {line.warnings.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {line.warnings.map((code) => (
                  <Badge
                    key={code}
                    variant="outline"
                    className="border-amber-300 bg-amber-50 text-amber-800"
                  >
                    <AlertTriangle className="mr-1 h-3 w-3" />
                    {WARNING_LABELS[code] ?? code}
                  </Badge>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>

      {summary.warnings.length > 0 && (
        <ul className="space-y-1 text-sm text-amber-800" aria-label="Warnings">
          {summary.warnings.map((warning, index) => (
            <li key={`${warning.code}-${index}`} className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {warning.filament_id != null && `Filament ${warning.filament_id}: `}
                {warning.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      {summary.blockers.length > 0 && (
        <ul className="space-y-1 text-sm text-destructive" aria-label="Blockers">
          {summary.blockers.map((blocker) => (
            <li key={blocker.code} className="flex gap-2">
              <Ban className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{blocker.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
