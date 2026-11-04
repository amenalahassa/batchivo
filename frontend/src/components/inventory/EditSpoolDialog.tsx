import { useState, useEffect, useMemo } from 'react'
import { useCurrency } from '@/hooks/useCurrency'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { spoolsApi } from '@/lib/api/spools'
import type { SpoolUpdate } from '@/types/spool'
import { apiErrorDetail } from '@/lib/apiError'

// Normalize brand/supplier names to prevent duplicates
const normalizeName = (name: string): string => {
  return name
    .toLowerCase()
    .replace(/\s+/g, '') // Remove all spaces
    .trim()
}

// Get display name (capitalize first letter of each word)
const getDisplayName = (name: string): string => {
  return name
    .split(/\s+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
    .trim()
}

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { canEditOperationalFigures } from '@/lib/pricing/permissions'

interface EditSpoolDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  spoolId: string | null
}

export function EditSpoolDialog({ open, onOpenChange, spoolId }: EditSpoolDialogProps) {
  // A viewer meets the form disabled rather than missing (T238, FR-007c).
  const { user } = useAuth()
  const canEdit = canEditOperationalFigures(user)

  const queryClient = useQueryClient()

  // Fetch the specific spool to edit
  const { data: spool, isLoading: loadingSpool } = useQuery({
    queryKey: ['spool', spoolId],
    queryFn: () => spoolsApi.get(spoolId!),
    enabled: !!spoolId && open,
  })

  // Fetch existing spools for supplier autocomplete
  const { data: spoolData } = useQuery({
    queryKey: ['spools', { page: 1, page_size: 100 }],
    queryFn: () => spoolsApi.list({ page: 1, page_size: 100 }),
  })

  // Form state
  const [formData, setFormData] = useState<Partial<SpoolUpdate>>({})

  // UI state for purchase info
  // Entered in the tenant's books currency; there is no per-spool one (T231).
  const { currency } = useCurrency()

  // Weight input mode - when true, user enters gross weight (what they read from scales)
  const [useGrossWeight, setUseGrossWeight] = useState(false)
  // Store the displayed weight value (could be gross or net depending on mode)
  const [displayedWeight, setDisplayedWeight] = useState<string>('')

  // Populate form when spool data loads
  useEffect(() => {
    if (spool && open) {
      setFormData({
        spool_id: spool.spool_id,
        initial_weight: spool.initial_weight,
        current_weight: spool.current_weight,
        empty_spool_weight: spool.empty_spool_weight || undefined,
        purchase_date: spool.purchase_date ? spool.purchase_date.split('T')[0] : undefined,
        purchase_price: spool.purchase_price || undefined,
        supplier: spool.supplier || '',
        storage_location: spool.storage_location || '',
        is_active: spool.is_active,
      })
      // Reset weight input mode and display value
      setUseGrossWeight(false)
      setDisplayedWeight(spool.current_weight.toString())
    }
  }, [spool, open])

  const uniqueSuppliers = useMemo(() => {
    if (!spoolData) return []

    const supplierMap = new Map<string, string>()
    spoolData.spools.forEach(spool => {
      if (spool.supplier) {
        const normalized = normalizeName(spool.supplier)
        if (!supplierMap.has(normalized)) {
          supplierMap.set(normalized, getDisplayName(spool.supplier))
        }
      }
    })

    return Array.from(supplierMap.values()).sort()
  }, [spoolData])

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: SpoolUpdate) => spoolsApi.update(spoolId!, data),
    onSuccess: () => {
      // Invalidate and refetch spools list
      queryClient.invalidateQueries({ queryKey: ['spools'] })
      queryClient.invalidateQueries({ queryKey: ['spool', spoolId] })
      // Close dialog
      onOpenChange(false)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    // Validation
    if (
      !formData.spool_id ||
      !formData.initial_weight ||
      formData.current_weight === undefined
    ) {
      alert('Please fill in all required fields')
      return
    }

    updateMutation.mutate(formData as SpoolUpdate)
  }

  // Generic over the field so a value must be what that field's own type
  // permits: a `Money` field takes a decimal string, never a number (T212).
  const handleInputChange = <K extends keyof SpoolUpdate>(field: K, value: SpoolUpdate[K]) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  // Calculate net weight from displayed weight (subtracts spool weight if in gross mode)
  const getNetWeight = (): number => {
    const enteredWeight = parseFloat(displayedWeight) || 0
    if (useGrossWeight && formData.empty_spool_weight) {
      return Math.max(0, enteredWeight - formData.empty_spool_weight)
    }
    return enteredWeight
  }

  // Handle weight input changes - updates both display and form data
  const handleWeightChange = (value: string) => {
    setDisplayedWeight(value)
    const numValue = parseFloat(value) || 0

    if (useGrossWeight && formData.empty_spool_weight) {
      // User entered gross weight, store net weight
      const netWeight = Math.max(0, numValue - formData.empty_spool_weight)
      setFormData((prev) => ({ ...prev, current_weight: netWeight }))
    } else {
      // User entered net weight directly
      setFormData((prev) => ({ ...prev, current_weight: numValue }))
    }
  }

  // Handle toggle between gross/net weight mode
  const handleWeightModeChange = (useGross: boolean) => {
    const currentNet = formData.current_weight || 0
    const spoolWeight = formData.empty_spool_weight || 0

    if (useGross && spoolWeight) {
      // Switching TO gross mode: display = net + spool
      setDisplayedWeight((currentNet + spoolWeight).toString())
    } else {
      // Switching TO net mode: display = net
      setDisplayedWeight(currentNet.toString())
    }
    setUseGrossWeight(useGross)
  }

  // Calculate remaining percentage for display using actual net weight
  const remainingPercentage = formData.current_weight && formData.initial_weight
    ? ((formData.current_weight / formData.initial_weight) * 100).toFixed(0)
    : '0'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Spool {spool?.spool_id}</DialogTitle>
          <DialogDescription>
            Update filament spool information and weight tracking.
          </DialogDescription>
        </DialogHeader>

        {loadingSpool ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="ml-3">Loading spool data...</span>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <fieldset disabled={!canEdit} className="m-0 min-w-0 space-y-4 border-0 p-0">
            {/* Required Fields */}
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="spool_id">
                    Spool ID <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="spool_id"
                    placeholder="FIL-001"
                    value={formData.spool_id}
                    onChange={(e) => handleInputChange('spool_id', e.target.value)}
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label>Filament</Label>
                  <div
                    className="min-h-10 flex items-center px-3 py-1 bg-muted rounded-md text-sm"
                    data-testid="spool-filament-type"
                  >
                    {spool?.filament_type
                      ? `${spool.filament_type.material_type_name} · ${spool.filament_type.brand} · ${spool.filament_type.color}${spool.filament_type.finish ? ` (${spool.filament_type.finish})` : ''}`
                      : '—'}
                  </div>
                  {/* Material, brand and colour belong to the filament type, shared by
                      every spool of it. The spool API does not take them, so they are
                      shown, not offered as fields that would not save. */}
                  <p className="text-xs text-muted-foreground">
                    Edit material, brand and colour on the Filaments page.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="empty_spool_weight">
                    Empty Spool Weight (g)
                  </Label>
                  <Input
                    id="empty_spool_weight"
                    type="number"
                    placeholder="250"
                    value={formData.empty_spool_weight || ''}
                    onChange={(e) => handleInputChange('empty_spool_weight', e.target.value ? parseFloat(e.target.value) : undefined)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Weight of the plastic spool without filament
                  </p>
                </div>
              </div>

              {/* Weight Mode Toggle (only show if empty_spool_weight is set) */}
              {formData.empty_spool_weight && (
                <div className="flex items-center gap-4 p-3 bg-blue-50 dark:bg-blue-950/30 rounded-lg border border-blue-200 dark:border-blue-800">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="use_gross_weight"
                      checked={useGrossWeight}
                      onChange={(e) => handleWeightModeChange(e.target.checked)}
                      className="h-4 w-4 rounded border-gray-300"
                    />
                    <Label htmlFor="use_gross_weight" className="text-sm font-normal cursor-pointer">
                      Enter gross weight (what you weigh on scales)
                    </Label>
                  </div>
                  {useGrossWeight && (
                    <span className="text-xs text-muted-foreground">
                      Will subtract {formData.empty_spool_weight}g spool weight
                    </span>
                  )}
                </div>
              )}

              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="initial_weight">
                    Initial Filament (g) <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="initial_weight"
                    type="number"
                    placeholder="1000"
                    value={formData.initial_weight}
                    onChange={(e) => handleInputChange('initial_weight', parseFloat(e.target.value))}
                    required
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="current_weight">
                    {useGrossWeight ? 'Gross Weight (g)' : 'Current Filament (g)'} <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="current_weight"
                    type="number"
                    step="0.1"
                    placeholder={useGrossWeight ? 'Weigh spool on scale' : '1000'}
                    value={displayedWeight}
                    onChange={(e) => handleWeightChange(e.target.value)}
                    required
                  />
                  {useGrossWeight && formData.empty_spool_weight && displayedWeight && (
                    <p className="text-xs text-muted-foreground">
                      Filament: {getNetWeight().toFixed(0)}g (gross - {formData.empty_spool_weight}g spool)
                    </p>
                  )}
                  {!useGrossWeight && (
                    <p className="text-xs text-muted-foreground">
                      {remainingPercentage}% remaining
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label className="text-muted-foreground">
                    {useGrossWeight ? 'Calculated Filament' : 'Gross Weight'}
                  </Label>
                  <div className="h-10 flex items-center px-3 bg-muted rounded-md text-sm">
                    {useGrossWeight
                      ? `${getNetWeight().toFixed(0)}g`
                      : formData.empty_spool_weight
                        ? `${((formData.current_weight || 0) + formData.empty_spool_weight).toFixed(0)}g`
                        : '—'
                    }
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {useGrossWeight
                      ? `${remainingPercentage}% remaining`
                      : formData.empty_spool_weight
                        ? 'Filament + spool'
                        : 'Set empty spool weight first'
                    }
                  </p>
                </div>
              </div>
            </div>

            {/* Optional Purchase Info */}
            <div className="border-t pt-4 space-y-4">
              <h4 className="text-sm font-medium">Purchase Information (Optional)</h4>

              <div className="grid grid-cols-3 gap-4">

                <div className="space-y-2">
                  <Label htmlFor="purchase_price">Price</Label>
                  <Input
                    id="purchase_price"
                    type="number"
                    step="0.01"
                    placeholder="8.30"
                    value={formData.purchase_price || ''}
                    onChange={(e) =>
                      // The typed string, not a double: this is the figure
                      // `landed_cost.py` allocates across and `cost_per_gram`
                      // divides, and the backend takes a `Decimal` (task T209).
                      handleInputChange('purchase_price', e.target.value || undefined)
                    }
                  />
                  <p className="text-xs text-muted-foreground">
                    {currency.code} per spool
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="purchase_date">Purchase Date</Label>
                  <Input
                    id="purchase_date"
                    type="date"
                    value={formData.purchase_date || ''}
                    onChange={(e) => handleInputChange('purchase_date', e.target.value || undefined)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="supplier">Supplier</Label>
                <Input
                  id="supplier"
                  list="supplier-list"
                  placeholder="Amazon, MatterHackers, etc."
                  value={formData.supplier || ''}
                  onChange={(e) => handleInputChange('supplier', getDisplayName(e.target.value))}
                  onBlur={(e) => handleInputChange('supplier', getDisplayName(e.target.value))}
                />
                <datalist id="supplier-list">
                  {uniqueSuppliers.map((supplier) => (
                    <option key={supplier} value={supplier} />
                  ))}
                </datalist>
              </div>
            </div>

            {/* Optional Organization */}
            <div className="border-t pt-4 space-y-4">
              <h4 className="text-sm font-medium">Organization (Optional)</h4>
              <div className="space-y-2">
                <Label htmlFor="storage_location">Storage Location</Label>
                <Input
                  id="storage_location"
                  placeholder="Shelf A3, Bin 12, etc."
                  value={formData.storage_location || ''}
                  onChange={(e) => handleInputChange('storage_location', e.target.value)}
                />
              </div>


              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="is_active"
                  checked={formData.is_active ?? true}
                  onChange={(e) => handleInputChange('is_active', e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300"
                />
                <Label htmlFor="is_active" className="text-sm font-normal cursor-pointer">
                  Spool is active (uncheck to mark as depleted/retired)
                </Label>
              </div>
            </div>

            {/* Error Display */}
            {updateMutation.isError && (
              <div className="bg-destructive/10 border border-destructive rounded-md p-3">
                <p className="text-sm text-destructive">
                  Failed to update spool: {apiErrorDetail(updateMutation.error)}
                </p>
              </div>
            )}

            </fieldset>

            {!canEdit && (

              <p className="text-sm text-muted-foreground" data-testid="read-only-notice">

                Changing this needs a member, admin or owner role.

              </p>

            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={updateMutation.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={updateMutation.isPending || !canEdit}>
                {updateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Update Spool
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
