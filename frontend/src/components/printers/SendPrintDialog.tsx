/**
 * SendPrintDialog — send a sliced plate to a Bambu printer, with confirmation (spec 011).
 *
 * Step 1 picks the sliced file (uploaded, or stored on a model), the plate and
 * the AMS slot of each filament, then asks the backend to prepare a summary.
 * Step 2 shows that summary; the print starts only when the operator presses
 * "Start print" within the confirmation window, after ticking "I have checked
 * the warnings" when the summary carries any (FR-004a). Nothing reaches the
 * printer before that.
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import {
  getModelFileDownloadUrl,
  getModelFiles,
  listModels,
  parse3mfFile,
  type ThreeMFPlateInfo,
} from '@/lib/api/models'
import { printSendErrorMessage } from '@/lib/api/printSends'
import { useConfirmPrintSend, usePreparePrintSend } from '@/hooks/usePrintSends'
import type { AmsMappingEntry, PrintSend, PrintSendPrepared, SlotRef } from '@/types/printSend'
import { PrintSendSummary } from './PrintSendSummary'

const SELECT_CLASS =
  'flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm'

/** Slot options: AMS 1–4 × slot 1–4, then the external spool holder. */
const SLOT_OPTIONS: { value: string; label: string }[] = [
  ...Array.from({ length: 16 }, (_, i) => ({
    value: `ams:${Math.floor(i / 4)}:${i % 4}`,
    label: `AMS ${Math.floor(i / 4) + 1} · slot ${(i % 4) + 1}`,
  })),
  { value: 'external', label: 'External spool' },
]

function toSlot(value: string): SlotRef {
  if (value === 'external') return { kind: 'external' }
  const [, ams, tray] = value.split(':')
  return { kind: 'ams', ams_id: Number(ams), tray_id: Number(tray) }
}

function defaultSlot(filamentId: number): string {
  return filamentId >= 1 && filamentId <= 16
    ? `ams:${Math.floor((filamentId - 1) / 4)}:${(filamentId - 1) % 4}`
    : 'external'
}

function secondsLeft(expiresAt: string, now: number): number {
  return Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000))
}

interface SendPrintDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  printerId: string
  printerName: string
}

export function SendPrintDialog({ open, onOpenChange, printerId, printerName }: SendPrintDialogProps) {
  const [source, setSource] = useState<'upload' | 'model'>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [modelId, setModelId] = useState('')
  const [modelFileId, setModelFileId] = useState('')
  const [attachToModelId, setAttachToModelId] = useState('')
  const [plates, setPlates] = useState<ThreeMFPlateInfo[]>([])
  const [plateIndex, setPlateIndex] = useState<number | null>(null)
  const [slots, setSlots] = useState<Record<number, string>>({})
  const [readError, setReadError] = useState<string | null>(null)
  const [reading, setReading] = useState(false)
  const [prepared, setPrepared] = useState<PrintSendPrepared | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [started, setStarted] = useState<PrintSend | null>(null)
  const [now, setNow] = useState(() => Date.now())

  const prepare = usePreparePrintSend(printerId)
  const confirm = useConfirmPrintSend(printerId)

  const { data: models } = useQuery({
    queryKey: ['models', 'send-print-picker'],
    queryFn: () => listModels({ limit: 100, is_active: true }),
    enabled: open,
  })
  const { data: modelFiles } = useQuery({
    queryKey: ['model-files', modelId],
    queryFn: () => getModelFiles(modelId),
    enabled: open && source === 'model' && Boolean(modelId),
  })
  const slicedFiles = (modelFiles ?? []).filter(
    (f) => f.is_sliced || f.original_filename.toLowerCase().endsWith('.gcode.3mf')
  )

  // Countdown of the confirmation window.
  useEffect(() => {
    if (!prepared) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [prepared])

  const reset = () => {
    setFile(null)
    setModelId('')
    setModelFileId('')
    setAttachToModelId('')
    setPlates([])
    setPlateIndex(null)
    setSlots({})
    setReadError(null)
    setPrepared(null)
    setAcknowledged(false)
    setStarted(null)
    prepare.reset()
    confirm.reset()
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }

  const loadPlates = async (content: File) => {
    setReading(true)
    setReadError(null)
    try {
      const parsed = await parse3mfFile(content)
      const usable = parsed.plates.filter((p) => (p.filaments ?? []).length > 0)
      if (usable.length === 0) {
        setReadError('No sliced plate found: export the plate from Bambu Studio (.gcode.3mf).')
      }
      setPlates(usable)
      const first = usable[0] ?? null
      setPlateIndex(first?.index ?? null)
      setSlots(
        Object.fromEntries(
          (first?.filaments ?? [])
            .filter((f) => f.id != null)
            .map((f) => [f.id as number, defaultSlot(f.id as number)])
        )
      )
    } catch (error) {
      setReadError(error instanceof Error ? error.message : 'Could not read the file.')
      setPlates([])
    } finally {
      setReading(false)
    }
  }

  const onFileChosen = (chosen: File | null) => {
    setFile(chosen)
    setPrepared(null)
    if (chosen) void loadPlates(chosen)
  }

  const onModelFileChosen = async (fileId: string) => {
    setModelFileId(fileId)
    setPrepared(null)
    const chosen = slicedFiles.find((f) => f.id === fileId)
    if (!chosen) return
    setReading(true)
    try {
      const response = await api.get<Blob>(getModelFileDownloadUrl(modelId, fileId), {
        responseType: 'blob',
        timeout: 120_000,
      })
      await loadPlates(new File([response.data], chosen.original_filename))
    } catch (error) {
      setReading(false)
      setReadError(printSendErrorMessage(error))
    }
  }

  const plate = useMemo(() => plates.find((p) => p.index === plateIndex) ?? null, [plates, plateIndex])
  const filaments = (plate?.filaments ?? []).filter((f) => f.id != null)

  const onPlateChosen = (index: number) => {
    setPlateIndex(index)
    const chosen = plates.find((p) => p.index === index)
    setSlots(
      Object.fromEntries(
        (chosen?.filaments ?? [])
          .filter((f) => f.id != null)
          .map((f) => [f.id as number, slots[f.id as number] ?? defaultSlot(f.id as number)])
      )
    )
  }

  const canPrepare =
    plate != null &&
    filaments.length > 0 &&
    (source === 'upload' ? file != null : Boolean(modelFileId)) &&
    !prepare.isPending

  const onPrepare = async () => {
    if (!plate) return
    const mapping: AmsMappingEntry[] = filaments.map((f) => ({
      filament_id: f.id as number,
      slot: toSlot(slots[f.id as number] ?? defaultSlot(f.id as number)),
    }))
    setAcknowledged(false)
    const result = await prepare.mutateAsync({
      plate: plate.index,
      mapping,
      file: source === 'upload' ? (file ?? undefined) : undefined,
      modelFileId: source === 'model' ? modelFileId : undefined,
      attachToModelId: source === 'upload' && attachToModelId ? attachToModelId : undefined,
    })
    setNow(Date.now())
    setPrepared(result)
  }

  const remaining = prepared ? secondsLeft(prepared.expires_at, now) : 0
  const busy = prepared?.blockers.some((b) => b.code === 'printer_busy') ?? false
  const canConfirm =
    prepared != null &&
    remaining > 0 &&
    !busy &&
    (!prepared.requires_acknowledgement || acknowledged) &&
    !confirm.isPending

  const onConfirm = async () => {
    if (!prepared) return
    const send = await confirm.mutateAsync({
      token: prepared.confirmation_token,
      acknowledge: prepared.requires_acknowledgement && acknowledged,
    })
    setStarted(send)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Send print — {printerName}</DialogTitle>
          <DialogDescription>
            Nothing reaches the printer until you confirm the summary.
          </DialogDescription>
        </DialogHeader>

        {started ? (
          <div className="flex items-start gap-3 rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
            <CheckCircle2 className="h-5 w-5 shrink-0" />
            <div>
              <p className="font-medium">Print started</p>
              <p>
                Plate {started.plate.index} of {started.file.name} is printing. Its status follows
                the printer; see Sends for its progress.
              </p>
            </div>
          </div>
        ) : prepared ? (
          <div className="space-y-4">
            <PrintSendSummary summary={prepared} />
            {prepared.requires_acknowledgement && (
              <div className="flex items-center gap-2">
                <Checkbox
                  id="acknowledge-warnings"
                  checked={acknowledged}
                  onCheckedChange={(value) => setAcknowledged(value === true)}
                />
                <Label htmlFor="acknowledge-warnings">I have checked the warnings</Label>
              </div>
            )}
            <p className="text-sm text-muted-foreground" aria-live="polite">
              {remaining > 0
                ? `Confirm within ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}`
                : 'This summary has expired. Prepare the send again.'}
            </p>
            {confirm.error && (
              <p className="text-sm text-destructive" role="alert">
                {printSendErrorMessage(confirm.error)}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex gap-2" role="radiogroup" aria-label="File source">
              <Button
                type="button"
                variant={source === 'upload' ? 'default' : 'outline'}
                size="sm"
                onClick={() => {
                  setSource('upload')
                  setPlates([])
                }}
              >
                Upload a file
              </Button>
              <Button
                type="button"
                variant={source === 'model' ? 'default' : 'outline'}
                size="sm"
                onClick={() => {
                  setSource('model')
                  setPlates([])
                }}
              >
                From a model
              </Button>
            </div>

            {source === 'upload' ? (
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="send-file">Sliced file (.gcode.3mf)</Label>
                  <input
                    id="send-file"
                    type="file"
                    accept=".3mf"
                    className="block w-full text-sm"
                    onChange={(e) => onFileChosen(e.target.files?.[0] ?? null)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="attach-model">Keep this file on a model (optional)</Label>
                  <select
                    id="attach-model"
                    className={SELECT_CLASS}
                    value={attachToModelId}
                    onChange={(e) => setAttachToModelId(e.target.value)}
                  >
                    <option value="">Don't keep it (deleted after the send)</option>
                    {(models?.models ?? []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor="send-model">Model</Label>
                  <select
                    id="send-model"
                    className={SELECT_CLASS}
                    value={modelId}
                    onChange={(e) => {
                      setModelId(e.target.value)
                      setModelFileId('')
                      setPlates([])
                    }}
                  >
                    <option value="">Choose a model</option>
                    {(models?.models ?? []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="send-model-file">Sliced file</Label>
                  <select
                    id="send-model-file"
                    className={SELECT_CLASS}
                    value={modelFileId}
                    disabled={!modelId}
                    onChange={(e) => void onModelFileChosen(e.target.value)}
                  >
                    <option value="">
                      {modelId && slicedFiles.length === 0 ? 'No sliced file on this model' : 'Choose a file'}
                    </option>
                    {slicedFiles.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.original_filename}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            {reading && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Reading the plates…
              </p>
            )}
            {readError && (
              <p className="text-sm text-destructive" role="alert">
                {readError}
              </p>
            )}

            {plates.length > 0 && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="send-plate">Plate</Label>
                  <select
                    id="send-plate"
                    className={SELECT_CLASS}
                    value={plateIndex ?? ''}
                    onChange={(e) => onPlateChosen(Number(e.target.value))}
                  >
                    {plates.map((p) => (
                      <option key={p.index} value={p.index}>
                        Plate {p.index}
                      </option>
                    ))}
                  </select>
                </div>
                {filaments.length === 0 ? (
                  <p className="text-sm text-destructive">
                    This plate's filaments are not numbered: re-slice it with Bambu Studio.
                  </p>
                ) : (
                  <fieldset className="space-y-2">
                    <legend className="text-sm font-medium">AMS slot for each filament</legend>
                    {filaments.map((f) => (
                      <div key={f.id} className="grid grid-cols-[1fr_12rem] items-center gap-2">
                        <Label htmlFor={`slot-${f.id}`} className="flex items-center gap-2">
                          {f.color && (
                            <span
                              className="inline-block h-3 w-3 rounded-full border"
                              style={{ backgroundColor: f.color }}
                              aria-hidden="true"
                            />
                          )}
                          Filament {f.id} · {f.type ?? '?'}
                          {f.grams != null && ` · ${f.grams} g`}
                        </Label>
                        <select
                          id={`slot-${f.id}`}
                          className={SELECT_CLASS}
                          value={slots[f.id as number] ?? defaultSlot(f.id as number)}
                          onChange={(e) =>
                            setSlots((current) => ({ ...current, [f.id as number]: e.target.value }))
                          }
                        >
                          {SLOT_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </fieldset>
                )}
              </div>
            )}

            {prepare.error && (
              <p className="text-sm text-destructive" role="alert">
                {printSendErrorMessage(prepare.error)}
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          {started ? (
            <Button onClick={() => handleOpenChange(false)}>Close</Button>
          ) : prepared ? (
            <>
              <Button variant="outline" onClick={() => setPrepared(null)}>
                Back
              </Button>
              <Button onClick={() => void onConfirm().catch(() => undefined)} disabled={!canConfirm}>
                {confirm.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Send className="mr-2 h-4 w-4" />
                )}
                Start print
              </Button>
            </>
          ) : (
            <Button onClick={() => void onPrepare().catch(() => undefined)} disabled={!canPrepare}>
              {prepare.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Prepare
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
