/**
 * PackagingSettings — the clearance kept around an item in its box (T030, FR-015).
 *
 * Two figures in mm: the space left on every side of an ordinary item, and
 * of a fragile one. Until the operator saves them the advisor uses defaults,
 * and the card says so (D8). The figures are decimal strings, as the API
 * sends them.
 */

import { useEffect, useState } from 'react'
import { Loader2, Package } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usePackagingSettings, useUpdatePackagingSettings } from '@/hooks/usePackaging'

const tenthOfMm = /^\d{1,4}(\.\d)?$/

interface PackagingSettingsProps {
  canEdit: boolean
}

export function PackagingSettings({ canEdit }: PackagingSettingsProps) {
  const { data: settings, isLoading } = usePackagingSettings()
  const update = useUpdatePackagingSettings()
  const [clearance, setClearance] = useState('')
  const [fragile, setFragile] = useState('')

  useEffect(() => {
    if (settings) {
      setClearance(settings.clearance_mm)
      setFragile(settings.fragile_clearance_mm)
    }
  }, [settings])

  const invalid = !tenthOfMm.test(clearance.trim()) || !tenthOfMm.test(fragile.trim())

  const save = (e: React.FormEvent) => {
    e.preventDefault()
    if (invalid) return
    update.mutate({ clearance_mm: clearance.trim(), fragile_clearance_mm: fragile.trim() })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Package className="h-5 w-5" />
          Packaging
        </CardTitle>
        <CardDescription>
          The space the packaging advisor leaves on every side of an item.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading || !settings ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-label="Loading packaging settings" />
        ) : (
          <form onSubmit={save} className="space-y-4">
            {!settings.configured && (
              <p className="text-sm text-muted-foreground">
                These are the defaults. Save them to make them your own.
              </p>
            )}
            <fieldset disabled={!canEdit} className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="clearance_mm">Clearance (mm)</Label>
                <Input
                  id="clearance_mm"
                  inputMode="decimal"
                  value={clearance}
                  onChange={(e) => setClearance(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="fragile_clearance_mm">Fragile clearance (mm)</Label>
                <Input
                  id="fragile_clearance_mm"
                  inputMode="decimal"
                  value={fragile}
                  onChange={(e) => setFragile(e.target.value)}
                />
              </div>
            </fieldset>
            {invalid && (
              <p className="text-sm text-destructive">
                Enter a length in mm, to at most one decimal place.
              </p>
            )}
            {update.isError && (
              <p className="text-sm text-destructive">Could not save the packaging settings.</p>
            )}
            {canEdit && (
              <Button type="submit" disabled={invalid || update.isPending}>
                {update.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save
              </Button>
            )}
          </form>
        )}
      </CardContent>
    </Card>
  )
}
