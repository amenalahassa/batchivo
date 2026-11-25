/**
 * A printer's fit calibrations: the values in force, and their history (spec 009, US3).
 *
 * One row per combination (material, filament, fit, orientation) with its
 * current value; the superseded values of that combination open below it.
 * Members record a new value; viewers read.
 */
import { Fragment, useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useCalibrations } from '@/hooks/usePreflight'
import { apiErrorDetail } from '@/lib/apiError'
import { FIT_TEXT, ORIENTATION_TEXT, PROVENANCE_TEXT, mmText } from './preflightText'
import { comboKey, groupCalibrations } from './preflightLogic'
import { RecordCalibrationForm } from './RecordCalibrationForm'

interface CalibrationsDialogProps {
  printerId: string
  printerName: string
  canWrite: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CalibrationsDialog({ printerId, printerName, canWrite, open, onOpenChange }: CalibrationsDialogProps) {
  const { calibrations, isLoading, error } = useCalibrations(printerId, open)
  const groups = useMemo(() => groupCalibrations(calibrations), [calibrations])
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Calibrations — {printerName}</DialogTitle>
          <DialogDescription>
            Measured fit clearances (mm per side). Preflight uses them before its generic rule.
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorDetail(error)}
          </p>
        ) : isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : groups.length === 0 ? (
          <p className="text-sm text-muted-foreground">No calibration recorded for this printer yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Material</TableHead>
                <TableHead>Fit</TableHead>
                <TableHead>Orientation</TableHead>
                <TableHead>Clearance</TableHead>
                <TableHead>Recorded</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map(({ current, history }) => {
                const key = comboKey(current)
                return (
                  <Fragment key={key}>
                    <TableRow>
                      <TableCell>
                        {current.material_code}
                        {current.filament_label && (
                          <span className="block text-xs text-muted-foreground">{current.filament_label}</span>
                        )}
                      </TableCell>
                      <TableCell>{FIT_TEXT[current.fit_type]}</TableCell>
                      <TableCell>{ORIENTATION_TEXT[current.orientation]}</TableCell>
                      <TableCell className="font-mono">
                        {mmText(current.value_mm)}{' '}
                        <Badge variant="outline" className="ml-1">
                          {PROVENANCE_TEXT[current.provenance]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(current.measured_at).toLocaleDateString()}
                        {current.recorded_by && <> · {current.recorded_by.name}</>}
                      </TableCell>
                      <TableCell className="text-right">
                        {history.length > 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs"
                            aria-expanded={expanded === key}
                            onClick={() => setExpanded(expanded === key ? null : key)}
                          >
                            History ({history.length})
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                    {expanded === key &&
                      history.map((old) => (
                        <TableRow key={old.id} className="bg-muted/40 text-muted-foreground">
                          <TableCell colSpan={3} className="text-xs">
                            Superseded {old.superseded_at ? new Date(old.superseded_at).toLocaleDateString() : ''}
                          </TableCell>
                          <TableCell className="font-mono text-xs">{mmText(old.value_mm)}</TableCell>
                          <TableCell className="text-xs">
                            {new Date(old.measured_at).toLocaleDateString()}
                            {old.recorded_by && <> · {old.recorded_by.name}</>}
                          </TableCell>
                          <TableCell className="text-xs">{old.notes}</TableCell>
                        </TableRow>
                      ))}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
        )}

        {canWrite && (
          <section className="space-y-2 border-t pt-3">
            <h3 className="text-sm font-semibold">Record a value</h3>
            <RecordCalibrationForm printerId={printerId} />
          </section>
        )}
      </DialogContent>
    </Dialog>
  )
}
