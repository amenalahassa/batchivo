/**
 * ModelForm Component
 *
 * Form for creating and editing models (printed items) with validation.
 */

import { useState, useMemo, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2, RefreshCw } from 'lucide-react'

import { createModel, updateModel, listModels, parse3mfFile, uploadModelFile, type ModelDetail, type ModelCreateRequest, type ModelUpdateRequest, type ThreeMFParseResponse } from '@/lib/api/models'
import { listDesigners } from '@/lib/api/designers'
import { useNextSKU } from '@/hooks/useSKU'
import { useModelCostProfile } from '@/hooks/usePricing'
import { ProvenanceBadge } from '@/components/pricing/ProvenanceBadge'

// Predefined options for Source and Machine
const PREDEFINED_SOURCES = [
  'Patreon',
  'Thangs.com',
  'Makerworld',
  'Thingiverse',
  'Printables',
]

const PREDEFINED_MACHINES = [
  'Bambulabs A1 Mini',
  'Bambulabs A1',
  'Bambulabs P2S',
  'Ender 3 v2',
]
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { AlertCircle, FileCheck2 } from 'lucide-react'

function formatPrintTime(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours === 0) return `${mins}m`
  if (mins === 0) return `${hours}h`
  return `${hours}h ${mins}m`
}

const modelFormSchema = z.object({
  sku: z.string().min(1, 'SKU is required').max(100, 'SKU must be 100 characters or less'),
  name: z.string().min(1, 'Name is required').max(200, 'Name must be 200 characters or less'),
  description: z.string().optional(),
  category: z.string().optional(),
  labor_hours: z.string().regex(/^\d+(\.\d{1,2})?$/, 'Must be a valid number').optional().default('0'),
  overhead_percentage: z.string().regex(/^\d+(\.\d{1,2})?$/, 'Must be between 0 and 100').optional().default('0'),
  is_active: z.boolean().optional().default(true),
  // Metadata fields
  designer: z.string().max(200).optional(),
  source: z.string().max(200).optional(),
  print_time_hours: z.string().regex(/^\d*$/, 'Must be a valid number').optional(),
  print_time_minutes: z.string().regex(/^\d*$/, 'Must be a valid number').optional(),
  prints_per_plate: z.string().regex(/^\d+$/, 'Must be a valid number').optional().default('1'),
  machine: z.string().max(100).optional(),
  last_printed_date: z.string().optional(),
  units_in_stock: z.string().regex(/^\d+$/, 'Must be a valid number').optional().default('0'),
})

type ModelFormValues = z.infer<typeof modelFormSchema>

interface ModelFormProps {
  model?: ModelDetail
  mode: 'create' | 'edit'
}

export function ModelForm({ model, mode }: ModelFormProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Where the print time and batch size came from. Telemetry makes a print
  // time observed, and an observed figure is refreshed from its source and
  // never typed over (FR-004): the server refuses the save with 409, so the
  // field is locked rather than offered (T262).
  const { profile: costProfile } = useModelCostProfile(mode === 'edit' ? model?.id : undefined)
  const originOf = (fieldName: string) =>
    costProfile?.origins.find((entry) => entry.field_name === fieldName)
  const isObserved = (fieldName: string) => originOf(fieldName)?.editable === false
  const printTimeLocked = isObserved('print_time_minutes')
  const printsPerPlateLocked = isObserved('prints_per_plate')
  const originBadge = (fieldName: string) => {
    const origin = originOf(fieldName)
    return origin ? (
      <ProvenanceBadge
        source={origin.source}
        asOf={origin.as_of}
        isStale={origin.is_stale}
        isDefault={!origin.as_of}
      />
    ) : null
  }

  // Auto-generate SKU for new models
  const { nextSKU, isLoading: isLoadingSKU, refetch: refetchSKU } = useNextSKU('MOD', mode === 'create')

  // State for custom input values
  const [customDesigner, setCustomDesigner] = useState('')
  const [customSource, setCustomSource] = useState('')
  const [customMachine, setCustomMachine] = useState('')

  // 3MF import auto-fill state (create mode only)
  const [isParsing3mf, setIsParsing3mf] = useState(false)
  const [parse3mfError, setParse3mfError] = useState<string | null>(null)
  const [parsedWeightGrams, setParsedWeightGrams] = useState<number | null>(null)
  const [uploadedThreeMfFile, setUploadedThreeMfFile] = useState<File | null>(null)
  const [threeMfResult, setThreeMfResult] = useState<ThreeMFParseResponse | null>(null)
  const [threeMfApplied, setThreeMfApplied] = useState(false)
  const [applySelection, setApplySelection] = useState({
    printTime: true,
    plateCount: true,
    weight: true,
  })
  // Which plates (by 1-based index) are included when combining a multi-plate file.
  const [selectedPlateIndices, setSelectedPlateIndices] = useState<Set<number>>(new Set())

  // Fetch existing models to get unique values for sources/machines
  const { data: modelsData } = useQuery({
    queryKey: ['models', { limit: 500 }],
    queryFn: () => listModels({ limit: 500 }),
  })

  // Fetch designers from API
  const { data: designersData } = useQuery({
    queryKey: ['designers', { limit: 100 }],
    queryFn: () => listDesigners({ limit: 100 }),
  })

  // Get designers from the Designer API (active designers only)
  const uniqueDesigners = useMemo(() => {
    const designers = designersData?.designers
      ?.filter((d) => d.is_active)
      ?.map((d) => d.name)
      ?.sort() || []
    return designers
  }, [designersData])

  const uniqueSources = useMemo(() => {
    const fromModels = modelsData?.models
      ?.map((m) => m.source)
      .filter((s): s is string => !!s && s.trim() !== '') || []
    const combined = [...new Set([...PREDEFINED_SOURCES, ...fromModels])]
    return combined.sort()
  }, [modelsData])

  const uniqueMachines = useMemo(() => {
    const fromModels = modelsData?.models
      ?.map((m) => m.machine)
      .filter((m): m is string => !!m && m.trim() !== '') || []
    const combined = [...new Set([...PREDEFINED_MACHINES, ...fromModels])]
    return combined.sort()
  }, [modelsData])

  const form = useForm<z.input<typeof modelFormSchema>, unknown, ModelFormValues>({
    resolver: zodResolver(modelFormSchema),
    defaultValues: {
      sku: model?.sku || '',
      name: model?.name || '',
      description: model?.description || '',
      category: model?.category || '',
      labor_hours: model?.labor_hours || '0',
      overhead_percentage: model?.overhead_percentage || '0',
      is_active: model?.is_active ?? true,
      designer: model?.designer || '',
      source: model?.source || '',
      print_time_hours: model?.print_time_minutes ? Math.floor(model.print_time_minutes / 60).toString() : '',
      print_time_minutes: model?.print_time_minutes ? (model.print_time_minutes % 60).toString() : '',
      prints_per_plate: model?.prints_per_plate?.toString() || '1',
      machine: model?.machine || '',
      last_printed_date: model?.last_printed_date || '',
      units_in_stock: model?.units_in_stock?.toString() || '0',
    },
  })

  // Auto-fill SKU when it's fetched (only in create mode)
  useEffect(() => {
    if (mode === 'create' && nextSKU && !form.getValues('sku')) {
      form.setValue('sku', nextSKU)
    }
  }, [mode, nextSKU, form])

  const createMutation = useMutation({
    mutationFn: (data: ModelCreateRequest) => createModel(data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
      if (parsedWeightGrams != null) {
        try {
          // Carried client-side only (research.md §5) - BOMEditor reads and
          // clears this the first time it opens for this model.
          sessionStorage.setItem(`model-weight-suggestion:${data.id}`, String(parsedWeightGrams))
        } catch {
          // sessionStorage unavailable (private browsing, etc.) - the
          // suggestion is a convenience, not critical, so just skip it.
        }
      }
      if (uploadedThreeMfFile) {
        // Attach the originally-uploaded .3mf so the model gets a ModelFile
        // record and the existing thumbnail-extraction path runs exactly as
        // it does for the pre-existing post-creation upload flow (FR-006).
        // Best-effort: a failure here shouldn't block navigation to the
        // model that was already successfully created.
        uploadModelFile(data.id, uploadedThreeMfFile, 'source_3mf').catch((err) => {
          console.error('Failed to attach the uploaded 3MF file to the new model:', err)
        })
      }
      navigate({ to: '/models/$modelId', params: { modelId: data.id } })
    },
  })

  const hasThreeMfPrefillData = (result: ThreeMFParseResponse) =>
    result.print_time_minutes != null || result.plate_count != null || result.filament_weight_grams != null

  const hasMultiplePlates = (result: ThreeMFParseResponse) => result.plates.length > 1

  // When a file has more than one plate, the maker can select which ones to
  // combine (e.g. printing plates 1 and 3 together as one batch). Combined
  // print time / weight are the sum of the selected plates; combined plate
  // count is how many were selected (maps to "Items per Plate" below, same
  // as the single-plate case always did).
  const getEffectiveThreeMfValues = (result: ThreeMFParseResponse, selected: Set<number>) => {
    if (!hasMultiplePlates(result)) {
      return {
        printTimeMinutes: result.print_time_minutes,
        weightGrams: result.filament_weight_grams,
        plateCount: result.plate_count,
      }
    }

    const chosen = result.plates.filter((p) => selected.has(p.index))
    const sum = (values: (number | null)[]) => {
      const present = values.filter((v): v is number => v != null)
      return present.length > 0 ? present.reduce((a, b) => a + b, 0) : null
    }

    return {
      printTimeMinutes: sum(chosen.map((p) => p.print_time_minutes)),
      weightGrams: sum(chosen.map((p) => p.filament_weight_grams)),
      plateCount: chosen.length > 0 ? chosen.length : null,
    }
  }

  const handle3mfUpload = async (file: File) => {
    setIsParsing3mf(true)
    setParse3mfError(null)
    setThreeMfResult(null)
    setThreeMfApplied(false)
    setParsedWeightGrams(null)
    try {
      const result = await parse3mfFile(file)
      setThreeMfResult(result)
      setApplySelection({ printTime: true, plateCount: true, weight: true })
      setSelectedPlateIndices(new Set(result.plates.map((p) => p.index)))
    } catch (err) {
      setParse3mfError(err instanceof Error ? err.message : 'Failed to parse 3MF file')
    } finally {
      setIsParsing3mf(false)
    }
  }

  const togglePlateSelected = (index: number) => {
    setSelectedPlateIndices((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const applyThreeMfResult = () => {
    if (!threeMfResult) return
    const dirtyFields = form.formState.dirtyFields
    const effective = getEffectiveThreeMfValues(threeMfResult, selectedPlateIndices)

    if (
      applySelection.printTime &&
      effective.printTimeMinutes != null &&
      !dirtyFields.print_time_hours &&
      !dirtyFields.print_time_minutes
    ) {
      form.setValue('print_time_hours', Math.floor(effective.printTimeMinutes / 60).toString())
      form.setValue('print_time_minutes', (effective.printTimeMinutes % 60).toString())
    }

    if (applySelection.plateCount && effective.plateCount != null && !dirtyFields.prints_per_plate) {
      form.setValue('prints_per_plate', effective.plateCount.toString())
    }

    if (applySelection.weight && effective.weightGrams != null) {
      setParsedWeightGrams(effective.weightGrams)
    }

    setThreeMfApplied(true)
  }

  const updateMutation = useMutation({
    mutationFn: (data: ModelUpdateRequest) => updateModel(model!.id, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
      queryClient.invalidateQueries({ queryKey: ['model', model!.id] })
      navigate({ to: '/models/$modelId', params: { modelId: data.id } })
    },
  })

  const onSubmit = (values: ModelFormValues) => {
    // Destructure to exclude print_time_hours (we convert to total minutes)
    const { print_time_hours, print_time_minutes, prints_per_plate, ...rest } = values

    // Handle __custom__ values - if still __custom__, use the custom input value
    const finalDesigner = values.designer === '__custom__' ? customDesigner.trim() : values.designer
    const finalSource = values.source === '__custom__' ? customSource.trim() : values.source
    const finalMachine = values.machine === '__custom__' ? customMachine.trim() : values.machine

    const data = {
      ...rest,
      description: values.description || undefined,
      category: values.category || undefined,
      labor_hours: values.labor_hours || '0',
      overhead_percentage: values.overhead_percentage || '0',
      designer: finalDesigner || undefined,
      source: finalSource || undefined,
      // A locked figure is not sent: it is the observed one, unchanged.
      print_time_minutes: !printTimeLocked && (print_time_hours || print_time_minutes)
        ? (parseInt(print_time_hours || '0') * 60) + parseInt(print_time_minutes || '0')
        : undefined,
      prints_per_plate: printsPerPlateLocked
        ? undefined
        : prints_per_plate ? parseInt(prints_per_plate) : 1,
      machine: finalMachine || undefined,
      last_printed_date: values.last_printed_date || undefined,
      units_in_stock: values.units_in_stock ? parseInt(values.units_in_stock) : 0,
    }

    if (mode === 'create') {
      createMutation.mutate(data)
    } else {
      updateMutation.mutate(data)
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        {/* Basic Information */}
        <Card>
          <CardHeader>
            <CardTitle>Basic Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="sku"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>SKU</FormLabel>
                    <FormControl>
                      <div className="flex gap-2">
                        <Input
                          placeholder={isLoadingSKU ? 'Loading...' : 'MOD-001'}
                          {...field}
                          disabled={mode === 'edit' || isLoadingSKU}
                        />
                        {mode === 'create' && (
                          <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            onClick={() => refetchSKU()}
                            disabled={isLoadingSKU}
                            title="Generate new SKU"
                          >
                            <RefreshCw className={`h-4 w-4 ${isLoadingSKU ? 'animate-spin' : ''}`} />
                          </Button>
                        )}
                      </div>
                    </FormControl>
                    <FormDescription>
                      {mode === 'create'
                        ? 'Auto-generated, but you can edit it'
                        : 'Unique model identifier'}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="Model name" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description (Optional)</FormLabel>
                  <FormControl>
                    <Textarea placeholder="Model description..." rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="category"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Category (Optional)</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value || undefined}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a category" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="models">Models</SelectItem>
                      <SelectItem value="parts">Parts</SelectItem>
                      <SelectItem value="tools">Tools</SelectItem>
                      <SelectItem value="accessories">Accessories</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        {/* Model Metadata */}
        <Card>
          <CardHeader>
            <CardTitle>Model Metadata</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
            <FormField
              control={form.control}
              name="designer"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Designer (Optional)</FormLabel>
                  <Select
                    value={field.value || ''}
                    onValueChange={(value) => {
                      if (value === '__custom__') {
                        field.onChange('__custom__')
                        setCustomDesigner('')
                      } else {
                        field.onChange(value)
                      }
                    }}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a designer" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {uniqueDesigners.map((designer) => (
                        <SelectItem key={designer} value={designer}>
                          {designer}
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">+ Add new designer</SelectItem>
                    </SelectContent>
                  </Select>
                  {field.value === '__custom__' && (
                    <Input
                      placeholder="Enter designer name"
                      value={customDesigner}
                      onChange={(e) => setCustomDesigner(e.target.value)}
                      onBlur={() => {
                        if (customDesigner.trim()) {
                          field.onChange(customDesigner.trim())
                        }
                      }}
                      className="mt-2"
                      autoFocus
                    />
                  )}
                  <FormDescription>Model designer name</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="source"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Source (Optional)</FormLabel>
                  <Select
                    value={field.value || ''}
                    onValueChange={(value) => {
                      if (value === '__custom__') {
                        field.onChange('__custom__')
                        setCustomSource('')
                      } else {
                        field.onChange(value)
                      }
                    }}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a source" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {uniqueSources.map((source) => (
                        <SelectItem key={source} value={source}>
                          {source}
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">+ Add new source</SelectItem>
                    </SelectContent>
                  </Select>
                  {field.value === '__custom__' && (
                    <Input
                      placeholder="Enter source name"
                      value={customSource}
                      onChange={(e) => setCustomSource(e.target.value)}
                      onBlur={() => {
                        if (customSource.trim()) {
                          field.onChange(customSource.trim())
                        }
                      }}
                      className="mt-2"
                      autoFocus
                    />
                  )}
                  <FormDescription>Where the model came from</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          {mode === 'create' && (
            <div className="rounded-md border border-dashed p-4 space-y-2">
              <label htmlFor="model-3mf-upload" className="text-sm font-medium">
                Auto-fill from .3mf file (optional)
              </label>
              <Input
                id="model-3mf-upload"
                type="file"
                accept=".3mf"
                disabled={isParsing3mf}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) {
                    // Captured regardless of parse outcome (FR-006) so it
                    // can still be attached to the model after creation.
                    setUploadedThreeMfFile(file)
                    void handle3mfUpload(file)
                  }
                  e.target.value = ''
                }}
              />
              <p className="text-sm text-muted-foreground">
                Parses the slicer's embedded print time, plate count, and filament weight. After
                parsing, you choose which values to apply to the form below.
              </p>
              {isParsing3mf && (
                <p className="text-sm text-muted-foreground flex items-center gap-1">
                  <Loader2 className="h-3 w-3 animate-spin" /> Parsing file...
                </p>
              )}

              {parse3mfError && (
                <p className="text-sm text-destructive flex items-start gap-1">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{parse3mfError}</span>
                </p>
              )}

              {threeMfResult && !hasThreeMfPrefillData(threeMfResult) && (
                <div className="rounded-md bg-muted p-3 text-sm space-y-1">
                  <p className="font-medium flex items-center gap-1">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    No print data found in &quot;{uploadedThreeMfFile?.name}&quot;
                  </p>
                  <p className="text-muted-foreground">
                    {threeMfResult.thumbnail_available
                      ? 'A thumbnail was extracted, but no print time, plate count, or filament weight was found. '
                      : 'Nothing could be extracted from this file. '}
                    This usually means the file was exported directly from CAD software (e.g.
                    Fusion 360) rather than sliced. To auto-fill these fields, open it in a
                    slicer — Bambu Studio, OrcaSlicer, or PrusaSlicer — slice it, then upload the
                    sliced .3mf here instead.
                  </p>
                </div>
              )}

              {threeMfResult && hasThreeMfPrefillData(threeMfResult) && (
                <div className="rounded-md border p-3 space-y-3">
                  <p className="text-sm font-medium flex items-center gap-1">
                    <FileCheck2 className="h-4 w-4 shrink-0" />
                    Found in &quot;{uploadedThreeMfFile?.name}&quot; — choose what to apply:
                  </p>

                  {hasMultiplePlates(threeMfResult) && (
                    <div className="space-y-1.5 border-b pb-3">
                      <p className="text-xs font-medium text-muted-foreground">
                        {threeMfResult.plates.length} plates found — select which to combine:
                      </p>
                      {threeMfResult.plates.map((plate) => (
                        <label key={plate.index} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={selectedPlateIndices.has(plate.index)}
                            disabled={threeMfApplied}
                            onCheckedChange={() => togglePlateSelected(plate.index)}
                          />
                          Plate {plate.index}:{' '}
                          {plate.print_time_minutes != null
                            ? formatPrintTime(plate.print_time_minutes)
                            : '—'}
                          {plate.filament_weight_grams != null && ` · ${plate.filament_weight_grams}g`}
                        </label>
                      ))}
                    </div>
                  )}

                  <div className="space-y-2">
                    {(() => {
                      const effective = getEffectiveThreeMfValues(threeMfResult, selectedPlateIndices)
                      const multi = hasMultiplePlates(threeMfResult)
                      return (
                        <>
                          {effective.printTimeMinutes != null && (
                            <label className="flex items-center gap-2 text-sm">
                              <Checkbox
                                checked={applySelection.printTime}
                                disabled={threeMfApplied}
                                onCheckedChange={(checked) =>
                                  setApplySelection((prev) => ({ ...prev, printTime: checked === true }))
                                }
                              />
                              {multi ? 'Combined print' : 'Print'} time:{' '}
                              {formatPrintTime(effective.printTimeMinutes)}
                            </label>
                          )}
                          {effective.plateCount != null && (
                            <label className="flex items-center gap-2 text-sm">
                              <Checkbox
                                checked={applySelection.plateCount}
                                disabled={threeMfApplied}
                                onCheckedChange={(checked) =>
                                  setApplySelection((prev) => ({ ...prev, plateCount: checked === true }))
                                }
                              />
                              Plates: {effective.plateCount}
                              {multi ? ' selected' : ''}
                            </label>
                          )}
                          {effective.weightGrams != null && (
                            <label className="flex items-center gap-2 text-sm">
                              <Checkbox
                                checked={applySelection.weight}
                                disabled={threeMfApplied}
                                onCheckedChange={(checked) =>
                                  setApplySelection((prev) => ({ ...prev, weight: checked === true }))
                                }
                              />
                              {multi ? 'Combined filament' : 'Filament'} weight: {effective.weightGrams}g
                              {' '}(suggested on the next step, after saving)
                            </label>
                          )}
                        </>
                      )
                    })()}
                  </div>
                  {threeMfApplied ? (
                    <p className="text-sm text-muted-foreground">Applied to the form below.</p>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      onClick={applyThreeMfResult}
                      disabled={hasMultiplePlates(threeMfResult) && selectedPlateIndices.size === 0}
                    >
                      Apply to form
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-5">
            <FormField
              control={form.control}
              name="print_time_hours"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    <span className="flex items-center gap-2">
                      <span>Plate Print Time</span>
                      {originBadge('print_time_minutes')}
                    </span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      min="0"
                      placeholder="0"
                      disabled={printTimeLocked}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>Hours</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="print_time_minutes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>&nbsp;</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      min="0"
                      max="59"
                      placeholder="0"
                      aria-label="Plate print time minutes"
                      disabled={printTimeLocked}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>Minutes</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="prints_per_plate"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    <span className="flex items-center gap-2">
                      <span>Items per Plate</span>
                      {originBadge('prints_per_plate')}
                    </span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      min="1"
                      placeholder="1"
                      disabled={printsPerPlateLocked}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>Batch size</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="machine"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Machine (Optional)</FormLabel>
                  <Select
                    value={field.value || ''}
                    onValueChange={(value) => {
                      if (value === '__custom__') {
                        field.onChange('__custom__')
                        setCustomMachine('')
                      } else {
                        field.onChange(value)
                      }
                    }}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a printer" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {uniqueMachines.map((machine) => (
                        <SelectItem key={machine} value={machine}>
                          {machine}
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">+ Add new printer</SelectItem>
                    </SelectContent>
                  </Select>
                  {field.value === '__custom__' && (
                    <Input
                      placeholder="Enter printer name"
                      value={customMachine}
                      onChange={(e) => setCustomMachine(e.target.value)}
                      onBlur={() => {
                        if (customMachine.trim()) {
                          field.onChange(customMachine.trim())
                        }
                      }}
                      className="mt-2"
                      autoFocus
                    />
                  )}
                  <FormDescription>Printer used</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="units_in_stock"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Units in Stock</FormLabel>
                  <FormControl>
                    <Input type="number" min="0" placeholder="0" {...field} />
                  </FormControl>
                  <FormDescription>Printed inventory</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          <FormField
            control={form.control}
            name="last_printed_date"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Last Printed Date (Optional)</FormLabel>
                <FormControl>
                  <Input type="date" {...field} />
                </FormControl>
                <FormDescription>Last time this was printed</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          </CardContent>
        </Card>

        {/* Cost Information */}
        <Card>
          <CardHeader>
            <CardTitle>Cost Information</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="labor_hours"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Labor Hours</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" placeholder="0.00" {...field} />
                    </FormControl>
                    <FormDescription>Hours of work (post-processing, assembly, etc.)</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="overhead_percentage"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Overhead Percentage</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" max="100" placeholder="0" {...field} />
                    </FormControl>
                    <FormDescription>% markup for overhead costs (0-100)</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </CardContent>
        </Card>

        {/* Status */}
        {mode === 'edit' && (
          <Card>
            <CardContent className="pt-6">
              <FormField
                control={form.control}
                name="is_active"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center justify-between">
                    <div className="space-y-0.5">
                      <FormLabel className="text-base">Active Status</FormLabel>
                      <FormDescription>
                        Inactive models are hidden from listings but not deleted
                      </FormDescription>
                    </div>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-4">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate({ to: model ? `/models/${model.id}` : '/models' })}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {mode === 'create' ? 'Create Model' : 'Save Changes'}
          </Button>
        </div>
      </form>
    </Form>
  )
}
