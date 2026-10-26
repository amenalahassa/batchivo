/**
 * DimensionsEditor -- an item's length × width × height in mm (FR-001).
 *
 * Used for a product, each of its size variants, and a model. It shows where
 * the figures came from -- entered by the operator, measured from a named
 * file, or inherited from the product -- and when (FR-002). A measurement
 * that differs from the figures in force is offered, never applied: adopting
 * it is the operator's act (FR-003).
 *
 * The three figures stay decimal strings from input to wire (Constitution
 * IV); Zod checks their shape, not their value as a float.
 */

import { useEffect, useState } from 'react'
import { z } from 'zod'
import { Loader2, Ruler } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useSetDimensions, type DimensionsTarget } from '@/hooks/usePackaging'
import type { Dimensions, DimensionsInput } from '@/types/packaging'

const AXES = [
  { key: 'length_mm', label: 'Length' },
  { key: 'width_mm', label: 'Width' },
  { key: 'height_mm', label: 'Height' },
] as const

type AxisKey = (typeof AXES)[number]['key']
type Draft = Record<AxisKey, string>

/** A positive length to 0.1 mm, as typed. */
function lengthField(label: string) {
  return z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .regex(/^\d+(\.\d)?$/, `${label} must be a number in mm, to at most one decimal place`)
    .refine((value) => /[1-9]/.test(value), `${label} must be greater than 0`)
}

const dimensionsSchema = z.object({
  length_mm: lengthField('Length'),
  width_mm: lengthField('Width'),
  height_mm: lengthField('Height'),
})

/** A measurement the operator may adopt in place of the figures in force. */
export interface MeasurementOffer {
  fileId: string
  fileName: string
  length_mm: string
  width_mm: string
  height_mm: string
}

interface DimensionsEditorProps {
  target: DimensionsTarget
  dimensions: Dimensions | null | undefined
  /** False for a viewer: the figures are shown and nothing is offered (FR-023). */
  canEdit: boolean
  /** Names of the files a measurement could have come from, by id. */
  fileNames?: Record<string, string>
  offer?: MeasurementOffer | null
  title?: string
}

function draftOf(dimensions: Dimensions | null | undefined): Draft {
  // An inherited figure is the product's: a variant starts empty so saving
  // is a deliberate override rather than a copy of the product's numbers.
  const own = dimensions && !dimensions.inherited ? dimensions : null
  return {
    length_mm: own?.length_mm ?? '',
    width_mm: own?.width_mm ?? '',
    height_mm: own?.height_mm ?? '',
  }
}

function formatSize(d: { length_mm: string | null; width_mm: string | null; height_mm: string | null }) {
  return `${d.length_mm} × ${d.width_mm} × ${d.height_mm} mm`
}

function sameSize(a: Dimensions | null | undefined, b: MeasurementOffer): boolean {
  if (!a || a.length_mm === null) return false
  return a.length_mm === b.length_mm && a.width_mm === b.width_mm && a.height_mm === b.height_mm
}

export function SourceBadge({
  dimensions,
  fileNames,
}: {
  dimensions: Dimensions | null | undefined
  fileNames?: Record<string, string>
}) {
  if (!dimensions || dimensions.length_mm === null) {
    return <Badge variant="outline">No dimensions</Badge>
  }
  if (dimensions.inherited) {
    return <Badge variant="outline">Inherited from product</Badge>
  }
  const when = dimensions.set_at ? new Date(dimensions.set_at).toLocaleDateString() : null
  if (dimensions.source === 'measured') {
    const file = dimensions.source_file_id ? fileNames?.[dimensions.source_file_id] : undefined
    return (
      <Badge variant="outline" className="bg-blue-500/10 text-blue-700 border-blue-200">
        Measured{file ? ` from ${file}` : ' from a model file'}
        {when ? ` · ${when}` : ''}
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="bg-green-500/10 text-green-700 border-green-200">
      Entered{when ? ` · ${when}` : ''}
    </Badge>
  )
}

export function DimensionsEditor({
  target,
  dimensions,
  canEdit,
  fileNames,
  offer,
  title = 'Dimensions',
}: DimensionsEditorProps) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(dimensions))
  const [errors, setErrors] = useState<Partial<Record<AxisKey, string>>>({})
  const mutation = useSetDimensions(target)

  useEffect(() => {
    setDraft(draftOf(dimensions))
  }, [dimensions])

  const save = (data: DimensionsInput) => {
    mutation.mutate(data, { onSuccess: () => setErrors({}) })
  }

  const onSave = () => {
    const parsed = dimensionsSchema.safeParse(draft)
    if (!parsed.success) {
      const next: Partial<Record<AxisKey, string>> = {}
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as AxisKey
        next[key] ??= issue.message
      }
      setErrors(next)
      return
    }
    setErrors({})
    save(parsed.data)
  }

  const onClear = () => save({ length_mm: null, width_mm: null, height_mm: null })

  const hasOwn = !!dimensions && dimensions.length_mm !== null && !dimensions.inherited
  const showOffer = !!offer && !sameSize(dimensions, offer)

  return (
    <div className="space-y-3" data-testid="dimensions-editor">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Ruler className="h-4 w-4 text-muted-foreground" />
          {title}
          {dimensions && dimensions.length_mm !== null && (
            <span className="font-normal text-muted-foreground">{formatSize(dimensions)}</span>
          )}
        </div>
        <SourceBadge dimensions={dimensions} fileNames={fileNames} />
      </div>

      {canEdit && (
        <>
          <div className="grid grid-cols-3 gap-2">
            {AXES.map(({ key, label }) => (
              <div key={key} className="space-y-1">
                <Label htmlFor={`${title}-${key}`} className="text-xs">
                  {label} (mm)
                </Label>
                <Input
                  id={`${title}-${key}`}
                  inputMode="decimal"
                  value={draft[key]}
                  aria-invalid={!!errors[key]}
                  onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
                />
                {errors[key] && <p className="text-xs text-destructive">{errors[key]}</p>}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={onSave} disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save
            </Button>
            {hasOwn && (
              <Button size="sm" variant="outline" onClick={onClear} disabled={mutation.isPending}>
                {target.kind === 'variant' ? 'Use product dimensions' : 'Clear'}
              </Button>
            )}
          </div>
          {mutation.isError && (
            <p className="text-xs text-destructive">
              Could not save: {(mutation.error as Error).message}
            </p>
          )}
        </>
      )}

      {showOffer && offer && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-dashed p-2 text-sm">
          <span>
            Measured {formatSize(offer)} from {offer.fileName}
          </span>
          {canEdit && (
            <Button
              size="sm"
              variant="outline"
              disabled={mutation.isPending}
              onClick={() =>
                save({ length_mm: null, width_mm: null, height_mm: null, adopt_file_id: offer.fileId })
              }
            >
              Use these
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
