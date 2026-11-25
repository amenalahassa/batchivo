/**
 * Record how a printed test piece did (spec 009, US4, clarification Q3).
 *
 * A model's test names the version it tested (required for a critical-zone or
 * full-part test). Measurements are rows of name, value and unit, sent as
 * written (values stay text, so "0.15" stays exact). A photo is optional.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useFileVersions } from '@/hooks/useModelFileVersions'
import { useRecordTestResult } from '@/hooks/usePreflight'
import { materialTypesApi } from '@/lib/api/spools'
import {
  ORIENTATIONS,
  TEST_KINDS,
  TEST_OUTCOMES,
  type Orientation,
  type TestKind,
  type TestOutcome,
} from '@/types/preflight'
import { measurementsOf, type MeasurementRow as Row } from './preflightLogic'
import { ORIENTATION_TEXT, OUTCOME_TEXT, TEST_KIND_TEXT, preflightErrorText } from './preflightText'

const SELECT = 'h-9 w-full rounded-md border bg-background px-2 text-sm'

interface RecordTestResultDialogProps {
  modelId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RecordTestResultDialog({ modelId, open, onOpenChange }: RecordTestResultDialogProps) {
  const { versions } = useFileVersions(modelId)
  const { data: materials = [] } = useQuery({
    queryKey: ['material-types'],
    queryFn: () => materialTypesApi.list(),
    enabled: open,
  })
  const record = useRecordTestResult()
  const active = versions.find((v) => v.is_active) ?? versions[0]
  const [kind, setKind] = useState<TestKind>('critical_zone')
  const [outcome, setOutcome] = useState<TestOutcome>('pass')
  const [versionId, setVersionId] = useState<string>('')
  const [materialId, setMaterialId] = useState('')
  const [orientation, setOrientation] = useState<Orientation | ''>('')
  const [failureMode, setFailureMode] = useState('')
  const [notes, setNotes] = useState('')
  const [rows, setRows] = useState<Row[]>([{ name: '', value: '', unit: '' }])
  const [photo, setPhoto] = useState<File | null>(null)
  const version = versionId || active?.id || ''

  const close = () => {
    record.reset()
    onOpenChange(false)
  }
  const setRow = (index: number, key: keyof Row, value: string) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)))

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Record a test print</DialogTitle>
          <DialogDescription>What was printed, how it did, and what was measured.</DialogDescription>
        </DialogHeader>
        <form
          id="record-test-result"
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            record.mutate(
              {
                kind,
                outcome,
                model_id: modelId,
                model_file_version_id: version || null,
                material_type_id: materialId || null,
                orientation: orientation || null,
                measurements: measurementsOf(rows),
                failure_mode: failureMode.trim() || null,
                notes: notes.trim() || null,
                photo,
              },
              { onSuccess: close }
            )
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="test-kind">Test</Label>
              <select id="test-kind" className={SELECT} value={kind} onChange={(e) => setKind(e.target.value as TestKind)}>
                {TEST_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {TEST_KIND_TEXT[k]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="test-outcome">Outcome</Label>
              <select
                id="test-outcome"
                className={SELECT}
                value={outcome}
                onChange={(e) => setOutcome(e.target.value as TestOutcome)}
              >
                {TEST_OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {OUTCOME_TEXT[o]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="test-version">Version tested</Label>
              <select id="test-version" className={SELECT} value={version} onChange={(e) => setVersionId(e.target.value)}>
                {versions.length === 0 && <option value="">No version uploaded</option>}
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                    {v.is_active ? ' (active)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="test-material">Material</Label>
              <select id="test-material" className={SELECT} value={materialId} onChange={(e) => setMaterialId(e.target.value)}>
                <option value="">Not said</option>
                {materials.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.code}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="test-orientation">Orientation</Label>
              <select
                id="test-orientation"
                className={SELECT}
                value={orientation}
                onChange={(e) => setOrientation(e.target.value as Orientation | '')}
              >
                <option value="">Not said</option>
                {ORIENTATIONS.map((o) => (
                  <option key={o} value={o}>
                    {ORIENTATION_TEXT[o]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="test-photo">Photo</Label>
              <Input
                id="test-photo"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>

          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">Measurements</legend>
            {rows.map((row, index) => (
              <div key={index} className="flex gap-1">
                <Input aria-label={`Measurement ${index + 1} name`} placeholder="load_kg" value={row.name} onChange={(e) => setRow(index, 'name', e.target.value)} />
                <Input aria-label={`Measurement ${index + 1} value`} placeholder="7" value={row.value} onChange={(e) => setRow(index, 'value', e.target.value)} />
                <Input aria-label={`Measurement ${index + 1} unit`} placeholder="kg" className="w-20" value={row.unit} onChange={(e) => setRow(index, 'unit', e.target.value)} />
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Remove measurement ${index + 1}`}
                  onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setRows((current) => [...current, { name: '', value: '', unit: '' }])}
            >
              <Plus className="mr-1 h-4 w-4" /> Add measurement
            </Button>
          </fieldset>

          <div className="space-y-1">
            <Label htmlFor="test-failure">Failure mode</Label>
            <Input
              id="test-failure"
              value={failureMode}
              maxLength={2000}
              placeholder="e.g. broke at the root at 7 kg"
              onChange={(e) => setFailureMode(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="test-notes">Notes</Label>
            <Textarea id="test-notes" value={notes} onChange={(e) => setNotes(e.target.value)} className="min-h-16" />
          </div>
          {record.error && (
            <p role="alert" className="text-sm text-destructive">
              {preflightErrorText(record.error)}
            </p>
          )}
        </form>
        <DialogFooter>
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" form="record-test-result" disabled={record.isPending}>
            {record.isPending ? 'Saving…' : 'Record result'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
