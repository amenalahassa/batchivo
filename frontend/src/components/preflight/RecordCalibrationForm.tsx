/**
 * Record a fit clearance for a printer (spec 009, US3).
 *
 * The value is typed and sent as a decimal string (mm per side, up to three
 * decimals, 0 to 2), so what the operator measured is what is stored. A new
 * value for a combination supersedes the current one; nothing is edited.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRecordCalibration } from '@/hooks/usePreflight'
import { materialTypesApi } from '@/lib/api/spools'
import {
  FIT_TYPES,
  ORIENTATIONS,
  type CalibrationProvenance,
  type FitType,
  type Orientation,
} from '@/types/preflight'
import { FIT_TEXT, ORIENTATION_TEXT, PROVENANCE_TEXT, isValidClearance, preflightErrorText } from './preflightText'

const SELECT = 'h-9 w-full rounded-md border bg-background px-2 text-sm'

interface RecordCalibrationFormProps {
  printerId: string
  onDone?: () => void
}

export function RecordCalibrationForm({ printerId, onDone }: RecordCalibrationFormProps) {
  const { data: materials = [] } = useQuery({
    queryKey: ['material-types'],
    queryFn: () => materialTypesApi.list(),
  })
  const record = useRecordCalibration(printerId)
  const [materialId, setMaterialId] = useState('')
  const [fit, setFit] = useState<FitType>('slide')
  const [orientation, setOrientation] = useState<Orientation>('vertical')
  const [value, setValue] = useState('')
  const [provenance, setProvenance] = useState<CalibrationProvenance>('measured')
  const [notes, setNotes] = useState('')
  const valid = isValidClearance(value)
  const material = materialId || materials[0]?.id || ''

  return (
    <form
      aria-label="Record a calibration"
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!valid || !material) return
        record.mutate(
          {
            material_type_id: material,
            fit_type: fit,
            orientation,
            value_mm: value.trim(),
            provenance,
            notes: notes.trim() || null,
          },
          {
            onSuccess: () => {
              setValue('')
              setNotes('')
              onDone?.()
            },
          }
        )
      }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="cal-material">Material</Label>
          <select id="cal-material" className={SELECT} value={material} onChange={(e) => setMaterialId(e.target.value)}>
            {materials.map((m) => (
              <option key={m.id} value={m.id}>
                {m.code}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="cal-fit">Fit</Label>
          <select id="cal-fit" className={SELECT} value={fit} onChange={(e) => setFit(e.target.value as FitType)}>
            {FIT_TYPES.map((f) => (
              <option key={f} value={f}>
                {FIT_TEXT[f]}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="cal-orientation">Orientation</Label>
          <select
            id="cal-orientation"
            className={SELECT}
            value={orientation}
            onChange={(e) => setOrientation(e.target.value as Orientation)}
          >
            {ORIENTATIONS.map((o) => (
              <option key={o} value={o}>
                {ORIENTATION_TEXT[o]}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="cal-value">Clearance per side (mm)</Label>
          <Input
            id="cal-value"
            inputMode="decimal"
            placeholder="0.15"
            value={value}
            aria-invalid={value !== '' && !valid}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cal-provenance">Provenance</Label>
          <select
            id="cal-provenance"
            className={SELECT}
            value={provenance}
            onChange={(e) => setProvenance(e.target.value as CalibrationProvenance)}
          >
            {(['measured', 'assumed'] as const).map((p) => (
              <option key={p} value={p}>
                {PROVENANCE_TEXT[p]}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2 space-y-1 sm:col-span-1">
          <Label htmlFor="cal-notes">Notes</Label>
          <Input id="cal-notes" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </div>
      {value !== '' && !valid && (
        <p className="text-sm text-destructive">Between 0 and 2 mm, at most three decimals (e.g. 0.15).</p>
      )}
      {record.error && (
        <p role="alert" className="text-sm text-destructive">
          {preflightErrorText(record.error)}
        </p>
      )}
      <Button type="submit" disabled={!valid || !material || record.isPending}>
        {record.isPending ? 'Saving…' : 'Record value'}
      </Button>
    </form>
  )
}
