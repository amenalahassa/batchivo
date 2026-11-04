/**
 * The activation review (spec 004, T031; FR-011, FR-012, clarification Q3).
 *
 * Making a version active, or choosing another print file for the active
 * version, never moves a recorded figure on its own: each figure that would
 * change is listed old → new with a checkbox, and only the checked ones are
 * written. A row that cannot be applied says why.
 */
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

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
import { useActivateFileVersion, useActivationPreview } from '@/hooks/useModelFileVersions'
import { apiErrorDetail } from '@/lib/apiError'
import { figureText } from './activationText'
import type { ActivationField, ActivationRow, FileVersion } from '@/types/model-file-version'

const FIELD_LABELS: Record<ActivationField, string> = {
  print_time_minutes: 'Plate print time',
  prints_per_plate: 'Items per plate',
  weight_grams: 'Filament weight',
  dimensions: 'Dimensions',
}

const TARGET_NOTES: Record<ActivationRow['target'], string | null> = {
  model: null,
  model_printer_config: 'for the planned printer',
  model_material: 'on the bill of materials',
  dimensions: null,
}

interface VersionActivationDialogProps {
  modelId: string
  version: FileVersion | null
  /** Set when the review is for choosing this print file (on the active version or with activation). */
  printFileId?: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone?: () => void
}

export function VersionActivationDialog({
  modelId,
  version,
  printFileId,
  open,
  onOpenChange,
  onDone,
}: VersionActivationDialogProps) {
  const { preview, isLoading, error } = useActivationPreview(
    modelId,
    open && version ? version.id : null,
    printFileId
  )
  const activate = useActivateFileVersion(modelId)
  const [checked, setChecked] = useState<Set<ActivationField>>(new Set())

  // Start with every applicable row checked: the operator unticks what to keep.
  useEffect(() => {
    if (preview) {
      setChecked(new Set(preview.rows.filter((r) => r.selectable).map((r) => r.field)))
    }
  }, [preview])

  if (!version) return null

  const changingPrintFile = version.is_active
  const title = changingPrintFile
    ? `Change the print file of version ${version.label}`
    : `Make version ${version.label} active`

  const toggle = (field: ActivationField, on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (on) next.add(field)
      else next.delete(field)
      return next
    })
  }

  const apply = async () => {
    await activate.mutateAsync({
      versionId: version.id,
      apply: preview ? preview.rows.filter((r) => checked.has(r.field)).map((r) => r.field) : [],
      printFileId,
    })
    onOpenChange(false)
    onDone?.()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Choose which figures to take from this version. Unchecked figures keep their current
            value. Orders already placed keep the cost they were placed at.
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Comparing with the figures in use…
          </div>
        )}
        {error && <p className="text-sm text-destructive">{apiErrorDetail(error)}</p>}

        {preview && (
          <div className="space-y-3">
            {preview.rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No figure would change: the version&apos;s figures match the ones in use.
              </p>
            ) : (
              <ul className="space-y-2" aria-label="Figures that would change">
                {preview.rows.map((row) => {
                  const id = `activation-${row.field}`
                  const note = TARGET_NOTES[row.target]
                  return (
                    <li key={row.field} className="flex items-start gap-2 rounded-md border p-2">
                      <Checkbox
                        id={id}
                        checked={row.selectable && checked.has(row.field)}
                        disabled={!row.selectable}
                        onCheckedChange={(on) => toggle(row.field, on === true)}
                        aria-label={FIELD_LABELS[row.field]}
                      />
                      <label htmlFor={id} className="text-sm flex-1">
                        <span className="font-medium">{FIELD_LABELS[row.field]}</span>
                        {note && <span className="text-muted-foreground"> {note}</span>}
                        <span className="block text-muted-foreground">
                          {figureText(row.field, row.current)} →{' '}
                          <span className="text-foreground">
                            {figureText(row.field, row.proposed)}
                          </span>
                        </span>
                        {row.field === 'dimensions' && preview.dimension_file_name && (
                          <span className="block text-xs text-muted-foreground">
                            Measured from {preview.dimension_file_name}
                          </span>
                        )}
                        {!row.selectable && row.reason && (
                          <span className="block text-xs text-amber-600">
                            Can&apos;t apply: {row.reason}
                          </span>
                        )}
                      </label>
                    </li>
                  )
                })}
              </ul>
            )}
            {preview.dimension_file_name &&
              !preview.rows.some((r) => r.field === 'dimensions') && (
                <p className="text-xs text-muted-foreground">
                  Dimensions come from {preview.dimension_file_name} and already match.
                </p>
              )}
            {preview.notices.map((notice) => (
              <p key={notice} className="text-sm text-amber-600">
                {notice}
              </p>
            ))}
          </div>
        )}

        {activate.error && (
          <p className="text-sm text-destructive">{apiErrorDetail(activate.error)}</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={apply} disabled={!preview || activate.isPending}>
            {activate.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {changingPrintFile ? 'Apply' : 'Make active'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
