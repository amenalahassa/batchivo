/**
 * BOMEditor Component
 *
 * Editor for managing model Bill of Materials (filament materials).
 */

import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { HelpCircle, Info, Loader2, Plus, Trash2 } from 'lucide-react'

import { addModelMaterial, removeModelMaterial, type ModelMaterial } from '@/lib/api/models'
import { spoolsApi } from '@/lib/api/spools'
import { formatMoney } from '@/lib/money'
import type { Money } from '@/types/pricing'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { SearchableSpoolSelect } from '@/components/inventory/SearchableSpoolSelect'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useAuth } from '@/contexts/AuthContext'
import { canEditOperationalFigures } from '@/lib/pricing/permissions'

const materialFormSchema = z.object({
  spool_id: z.string().uuid('Must select a spool'),
  weight_grams: z.string().regex(/^\d+(\.\d{1,2})?$/, 'Must be a valid number'),
  // Empty costs the line at the spool's landed per-gram figure, which the
  // server derives with the purchase's shipping and tax (T254). A figure here
  // is an override the operator owns.
  cost_per_gram: z
    .string()
    .regex(/^(\d+(\.\d{1,4})?)?$/, 'Must be a valid number'),
})

type MaterialFormValues = z.infer<typeof materialFormSchema>

interface BOMEditorProps {
  modelId: string
  materials: ModelMaterial[]
}

export function BOMEditor({ modelId, materials }: BOMEditorProps) {
  // A viewer sees the bill of materials with its controls disabled (T238).
  const { user } = useAuth()
  const canEdit = canEditOperationalFigures(user)

  const [dialogOpen, setDialogOpen] = useState(false)
  const queryClient = useQueryClient()

  // Fetch available spools (backend limits to 100 per page)
  const { data: spoolsData } = useQuery({
    queryKey: ['spools', { page_size: 100 }],
    queryFn: () => spoolsApi.list({ page_size: 100 }),
  })

  const form = useForm<z.input<typeof materialFormSchema>, unknown, MaterialFormValues>({
    resolver: zodResolver(materialFormSchema),
    defaultValues: {
      spool_id: '',
      weight_grams: '',
      cost_per_gram: '',
    },
  })

  // Consume a 3MF-parsed weight suggestion stashed by ModelForm (research.md §5),
  // if any, pre-filling weight_grams exactly once. Never pre-selects a spool.
  useEffect(() => {
    const key = `model-weight-suggestion:${modelId}`
    try {
      const stored = sessionStorage.getItem(key)
      if (stored === null) return
      sessionStorage.removeItem(key)
      const suggestedWeight = parseFloat(stored)
      if (!Number.isNaN(suggestedWeight) && !form.formState.dirtyFields.weight_grams) {
        form.setValue('weight_grams', suggestedWeight.toString())
      }
    } catch {
      // sessionStorage unavailable - no suggestion, falls back to manual entry
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId])

  const addMutation = useMutation({
    mutationFn: (data: MaterialFormValues) =>
      addModelMaterial(modelId, {
        spool_id: data.spool_id,
        weight_grams: data.weight_grams,
        ...(data.cost_per_gram ? { cost_per_gram: data.cost_per_gram } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['model', modelId] })
      form.reset()
      setDialogOpen(false)
    },
  })

  const removeMutation = useMutation({
    mutationFn: (materialId: string) => removeModelMaterial(modelId, materialId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['model', modelId] })
    },
  })

  // The spool's landed figure, as the server derived it, shown as the
  // placeholder so the operator sees what an empty override means.
  const selectedSpool = spoolsData?.spools.find((s) => s.id === form.watch('spool_id'))
  const selectedLandedHint = selectedSpool?.cost_per_gram ?? '0.0000'

  const onSubmit = (values: MaterialFormValues) => {
    addMutation.mutate(values)
  }

  // Four places, because a per-gram filament cost is fractions of a penny. It
  // renders the decimal string the API sent and never becomes a double
  // (Constitution IV, task T151).
  const formatCurrency = (value: Money | null | undefined) =>
    formatMoney(value, '£', { places: 4 })

  return (
    <div className="space-y-4">
      {/* Info card explaining what to enter */}
      <Alert className="border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950">
        <Info className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        <AlertTitle className="text-blue-800 dark:text-blue-200">Per-Unit Filament Only</AlertTitle>
        <AlertDescription className="text-blue-700 dark:text-blue-300">
          Enter the filament weight for <strong>one unit</strong> of this model.
          Only include the model's filament - purge tower and flush waste are tracked separately when you create a production run.
        </AlertDescription>
      </Alert>

      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Bill of Materials</h3>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button size="sm" disabled={!canEdit}>
              <Plus className="mr-2 h-4 w-4" />
              Add Material
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add Material</DialogTitle>
              <DialogDescription>Add a filament material to this model's BOM</DialogDescription>
            </DialogHeader>
            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                <FormField
                  control={form.control}
                  name="spool_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Spool</FormLabel>
                      <FormControl>
                        <SearchableSpoolSelect
                          spools={spoolsData?.spools ?? []}
                          value={field.value}
                          onValueChange={(value) => {
                            field.onChange(value)
                          }}
                          placeholder="Search for a spool..."
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="weight_grams"
                  render={({ field }) => (
                    <FormItem>
                      <div className="flex items-center gap-1">
                        <FormLabel>Weight (grams)</FormLabel>
                        <Popover>
                          <PopoverTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-5 w-5 p-0">
                              <HelpCircle className="h-4 w-4 text-muted-foreground" />
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent className="w-80">
                            <div className="space-y-2">
                              <h4 className="font-medium">Multi-Color Example</h4>
                              <p className="text-sm text-muted-foreground">
                                A dragon with 2 colors printed at 4 per plate:
                              </p>
                              <ul className="text-sm text-muted-foreground space-y-1">
                                <li>• Body (Blue PLA): <strong>45g per unit</strong></li>
                                <li>• Wings (Gold PLA): <strong>12g per unit</strong></li>
                              </ul>
                              <p className="text-sm text-muted-foreground pt-2 border-t">
                                The purge tower (~15g) and flush waste are entered later when creating a production run.
                              </p>
                            </div>
                          </PopoverContent>
                        </Popover>
                      </div>
                      <FormControl>
                        <Input type="number" step="0.01" placeholder="0.00" {...field} />
                      </FormControl>
                      <FormDescription>Per-unit filament weight (model only, no tower/purge)</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="cost_per_gram"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Cost per Gram override (£)</FormLabel>
                      <FormControl>
                        <Input type="number" step="0.0001" placeholder={selectedLandedHint} {...field} />
                      </FormControl>
                      <FormDescription>
                        Leave empty to use the spool's landed cost per usable gram, which follows
                        its price, purchase shipping and remainder.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={addMutation.isPending}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={addMutation.isPending}>
                    {addMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Add Material
                  </Button>
                </DialogFooter>
              </form>
            </Form>
          </DialogContent>
        </Dialog>
      </div>

      {!materials || materials.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          No materials added yet. Click "Add Material" to get started.
        </div>
      ) : (
        <div className="space-y-2">
          {materials?.map((material) => {
            // Look up spool details from the spools data
            const spool = spoolsData?.spools.find((s) => s.id === material.spool_id)
            const spoolDisplay = spool
              ? `${spool.spool_id} - ${spool.material_type_name} (${spool.color})`
              : material.spool_id
            return (
            <div key={material.id} className="flex items-center justify-between rounded-lg border bg-card p-4">
              <div className="space-y-1">
                <div className="font-medium">{spoolDisplay}</div>
                <div className="text-sm text-muted-foreground">
                  {parseFloat(material.weight_grams).toFixed(2)}g @{' '}
                  {material.resolved_cost_per_gram === null
                    ? 'cost unknown'
                    : `${formatCurrency(material.resolved_cost_per_gram)}/g`}
                  {material.cost_per_gram !== null ? ' (override)' : ' (from spool)'}
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <div className="font-semibold">
                    {/* The server's figure: weight times the resolved per-gram cost (T254). */}
                    {material.line_cost === null ? '—' : formatCurrency(material.line_cost)}
                  </div>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="ghost" size="sm" disabled={removeMutation.isPending || !canEdit}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Remove Material</AlertDialogTitle>
                      <AlertDialogDescription>
                        Are you sure you want to remove this material from the BOM?
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => removeMutation.mutate(material.id)}>Remove</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
