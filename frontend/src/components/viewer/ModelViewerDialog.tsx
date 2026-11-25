/**
 * The 3D viewer for a model file (spec 004, T042, T053; FR-017 to FR-030).
 *
 * Loaded lazily (its own chunk, with three.js) from the files card. It fetches
 * the file, parses it in a worker, and draws a mesh as a solid or a sliced
 * file as toolpaths with a layer slider and, for a multi-plate .gcode.3mf, a
 * plate picker. It draws the planned printer's bed, says when the file was
 * sliced for another printer, filament or nozzle, and when only a reduced
 * preview is shown. Notes are pinned on the part and listed beside it.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, MapPin } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { getModelProductionDefaults, type ModelFile } from '@/lib/api/models'
import { getPrinter } from '@/lib/api/printers'
import { useModelCostProfile } from '@/hooks/usePricing'
import {
  useCarryFileNoteForward,
  useCreateFileNote,
  useFileNotes,
  useUpdateFileNote,
} from '@/hooks/useModelFileNotes'
import { apiErrorDetail } from '@/lib/apiError'
import { fetchModelFile, parseInWorker } from '@/lib/viewer/parseInWorker'
import { toolpathBounds } from '@/lib/viewer/gcode'
import { LOCAL_REFERENCE_TEXT, mismatches, NO_PLANNED_MACHINE, REDUCED_PREVIEW } from '@/lib/viewer/notices'
import { meshBounds } from '@/lib/viewer/mesh'
import type { ParseResult } from '@/workers/modelParse'
import type { FileNote, FileVersion, Vector3 } from '@/types/model-file-version'

import { ViewerCanvas, type Bed } from './ViewerCanvas'
import { MeshView } from './MeshView'
import type { PartPick } from './pick'
import { ToolpathView } from './ToolpathView'
import { NotePins } from './NotePins'
import { NotesPanel } from './NotesPanel'

export interface ModelViewerDialogProps {
  modelId: string
  file: ModelFile
  versions: FileVersion[]
  canWrite: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Where to draw a mesh: centred on the bed, resting on it (a toolpath stays where it was sliced). */
function placement(result: ParseResult, bed: Bed | null) {
  if (result.kind === 'empty') return { offset: [0, 0, 0] as Vector3, target: [0, 0, 0] as Vector3, extent: 50 }
  const { min, max } =
    result.kind === 'mesh' ? meshBounds(result.mesh) : toolpathBounds(result.toolpath)
  const extent = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1)
  if (result.kind === 'toolpath') {
    return {
      offset: [0, 0, 0] as Vector3,
      target: [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2] as Vector3,
      extent,
    }
  }
  const cx = bed ? bed.x / 2 : 0
  const cy = bed ? bed.y / 2 : 0
  const offset: Vector3 = [cx - (min[0] + max[0]) / 2, cy - (min[1] + max[1]) / 2, -min[2]]
  return { offset, target: [cx, cy, (max[2] - min[2]) / 2] as Vector3, extent }
}

export default function ModelViewerDialog({
  modelId,
  file,
  versions,
  canWrite,
  open,
  onOpenChange,
}: ModelViewerDialogProps) {
  const isLocal = file.file_location === 'local_reference'
  const [buffer, setBuffer] = useState<ArrayBuffer | null>(null)
  const [plate, setPlate] = useState<number | undefined>(undefined)
  const [result, setResult] = useState<ParseResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [layer, setLayer] = useState(0)
  const [mode, setMode] = useState<'view' | 'add' | { move: FileNote }>('view')
  const [draft, setDraft] = useState<PartPick | null>(null)
  const [includeArchived, setIncludeArchived] = useState(false)

  // The planned printer gives the bed; the bill of materials the filament.
  const { profile } = useModelCostProfile(modelId)
  const plannedId = profile?.planned_printer_id ?? null
  const { data: printer } = useQuery({
    queryKey: ['printer', plannedId],
    queryFn: () => getPrinter(plannedId as string),
    enabled: Boolean(plannedId),
  })
  const { data: defaults } = useQuery({
    queryKey: ['model-production-defaults', modelId],
    queryFn: () => getModelProductionDefaults(modelId),
  })
  const bedX = printer?.bed_size_x_mm
  const bedY = printer?.bed_size_y_mm
  const bed: Bed | null = useMemo(() => (bedX && bedY ? { x: bedX, y: bedY } : null), [bedX, bedY])

  useEffect(() => {
    if (isLocal || !open) return
    const controller = new AbortController()
    setError(null)
    fetchModelFile(modelId, file.id, controller.signal)
      .then(setBuffer)
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'The file could not be opened')
      })
    return () => controller.abort()
  }, [modelId, file.id, isLocal, open])

  useEffect(() => {
    if (!buffer) return
    let cancelled = false
    setResult(null)
    parseInWorker(buffer, file.original_filename, plate)
      .then((parsed) => {
        if (cancelled) return
        setResult(parsed)
        if (parsed.kind === 'toolpath') setLayer(Math.max(0, parsed.toolpath.layers.length - 1))
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'The file could not be read'))
    return () => {
      cancelled = true
    }
  }, [buffer, plate, file.original_filename])

  const { notes } = useFileNotes(
    modelId,
    { ghosts_for_file_id: file.id, include_archived: includeArchived || undefined },
    open
  )
  const createNote = useCreateFileNote(modelId)
  const updateNote = useUpdateFileNote(modelId)
  const carryNote = useCarryFileNoteForward(modelId)
  const noteError = createNote.error ?? updateNote.error ?? carryNote.error

  const version = versions.find((v) => v.id === file.version_id) ?? null
  const place = useMemo(() => (result ? placement(result, bed) : null), [result, bed])
  const notices = useMemo(() => {
    const out: string[] = []
    if (!plannedId) out.push(NO_PLANNED_MACHINE)
    if (result?.kind === 'toolpath') {
      out.push(...mismatches(result.toolpath.header, printer ?? null, (defaults?.bom_materials ?? []).map((m) => m.material_type_code)))
    }
    if (result && result.kind !== 'empty' && result.reduced) out.push(REDUCED_PREVIEW)
    return out
  }, [plannedId, result, printer, defaults])

  const handlePick = (pick: PartPick) => {
    if (mode === 'add') {
      setDraft(pick)
    } else if (typeof mode === 'object') {
      updateNote.mutate({ noteId: mode.move.id, position: pick.position, normal: pick.normal })
      setMode('view')
    }
  }
  const picking = canWrite && mode !== 'view'

  const actions = {
    onResolve: (note: FileNote) =>
      updateNote.mutate({ noteId: note.id, status: 'resolved', resolved_in_version_id: file.version_id ?? undefined }),
    onCarryForward: (note: FileNote) => carryNote.mutate({ noteId: note.id, targetFileId: file.id }),
    onMove: (note: FileNote) => setMode({ move: note }),
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl w-[calc(100vw-2rem)] max-h-[95vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="truncate">{file.original_filename}</DialogTitle>
          <DialogDescription>
            {version ? `Version ${version.label}${version.is_active ? ' (active)' : ''}` : 'Model file'}
          </DialogDescription>
        </DialogHeader>

        {isLocal ? (
          <p className="text-sm text-muted-foreground" role="status">
            {LOCAL_REFERENCE_TEXT}
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-[1fr_300px]">
            <div className="min-w-0 space-y-2">
              {notices.map((n) => (
                <p key={n} className="text-sm text-amber-600" role="status">
                  {n}
                </p>
              ))}
              {error && <p className="text-sm text-destructive">{error}</p>}
              {!error && !result && (
                <div className="flex h-[50vh] items-center justify-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Opening the file…
                </div>
              )}
              {result?.kind === 'empty' && <p className="text-sm text-muted-foreground">{result.message}</p>}
              {result && result.kind !== 'empty' && place && (
                <>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    {result.kind === 'toolpath' && result.plates.length > 1 && (
                      <label className="flex items-center gap-1">
                        Plate
                        <select
                          aria-label="Plate"
                          className="rounded border bg-background px-1 py-0.5"
                          value={result.plate ?? ''}
                          onChange={(e) => setPlate(Number(e.target.value))}
                        >
                          {result.plates.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {canWrite && (
                      <Button
                        type="button"
                        size="sm"
                        variant={mode === 'add' ? 'default' : 'outline'}
                        onClick={() => {
                          setMode(mode === 'add' ? 'view' : 'add')
                          setDraft(null)
                        }}
                      >
                        <MapPin className="mr-1 h-4 w-4" />
                        {mode === 'add' ? 'Click the part…' : 'Add note'}
                      </Button>
                    )}
                    {typeof mode === 'object' && (
                      <span className="text-muted-foreground">
                        Click the new spot for note {mode.move.number}{' '}
                        <button type="button" className="underline" onClick={() => setMode('view')}>
                          Cancel
                        </button>
                      </span>
                    )}
                  </div>
                  <div className="h-[55vh] min-h-[280px] rounded-md border bg-muted/30">
                    <ViewerCanvas bed={bed} target={place.target} extent={place.extent}>
                      <group position={place.offset}>
                        {result.kind === 'mesh' ? (
                          <MeshView mesh={result.mesh} onPick={picking ? handlePick : undefined} />
                        ) : (
                          <ToolpathView toolpath={result.toolpath} layer={layer} onPick={picking ? handlePick : undefined} />
                        )}
                        <NotePins
                          notes={notes.filter((n) => !n.archived_at)}
                          canWrite={canWrite}
                          draft={draft}
                          onDraftCancel={() => setDraft(null)}
                          onDraftSave={(text) => {
                            if (!draft) return
                            createNote.mutate(
                              {
                                fileId: file.id,
                                position: draft.position,
                                normal: draft.normal,
                                layer: draft.layer ?? null,
                                text,
                              },
                              { onSuccess: () => setDraft(null) }
                            )
                            setMode('view')
                          }}
                          {...actions}
                        />
                      </group>
                    </ViewerCanvas>
                  </div>
                  {result.kind === 'toolpath' && result.toolpath.layers.length > 1 && (
                    <label className="flex items-center gap-2 text-sm">
                      <span className="whitespace-nowrap">
                        Layer {layer + 1} / {result.toolpath.layers.length}
                      </span>
                      <input
                        type="range"
                        aria-label="Layer"
                        className="w-full"
                        min={0}
                        max={result.toolpath.layers.length - 1}
                        value={layer}
                        onChange={(e) => setLayer(Number(e.target.value))}
                      />
                    </label>
                  )}
                </>
              )}
            </div>
            <div className="min-w-0">
              {noteError && <p className="mb-2 text-sm text-destructive">{apiErrorDetail(noteError)}</p>}
              <NotesPanel
                notes={notes}
                canWrite={canWrite}
                includeArchived={includeArchived}
                onIncludeArchivedChange={setIncludeArchived}
                onResolve={actions.onResolve}
                onCarryForward={actions.onCarryForward}
                onReopen={(note) => updateNote.mutate({ noteId: note.id, status: 'open' })}
                onDismiss={(note, reason) =>
                  updateNote.mutate({ noteId: note.id, status: 'dismissed', dismissal_reason: reason })
                }
              />
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
