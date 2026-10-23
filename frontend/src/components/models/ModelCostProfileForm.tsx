/**
 * ModelCostProfileForm — the figures that decide what printing this costs.
 *
 * Tier 1 taught the engine to cost purge waste, a failure premium and a
 * four-way labour split. Nothing could enter them, so every item sat at its
 * migration defaults: waste 0, yield 1.0, per-part, the split 0 — which is the
 * superseded model's answer wearing the look of a neutral default. This form
 * is the write path FR-007b requires.
 *
 * Three things it is deliberate about:
 *
 * 1. **A blank field is "not entered", never zero.** A zero purge weight is a
 *    claim that priming a plate consumes nothing; an empty field is the
 *    operator not having weighed it yet, and the breakdown says which (FR-001,
 *    FR-019).
 * 2. **Every figure shows where it came from.** A measured figure past the
 *    tenant's staleness threshold is flagged and still shown, because an
 *    operator with an old number can judge it and one with a blank cannot
 *    (FR-005). An observed figure is read-only: it is refreshed from its
 *    source, not typed over (FR-004).
 * 3. **The failure mode is explained, not just offered.** The same yield
 *    figure means different things under each mode — per-part divides by `y`,
 *    per-plate by `y^N` — so a plate of four parts costs more under per-plate
 *    at the same yield (FR-015a–e). Picking the wrong one is a silent error,
 *    so the consequence is written beside the choice.
 */

import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { AlertCircle, Loader2, SlidersHorizontal } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { ProvenanceBadge } from '@/components/pricing/ProvenanceBadge'
import { useModelCostProfile, useUpdateModelCostProfile } from '@/hooks/usePricing'
import type { CostProfileFieldOrigin, ModelCostProfileUpdate } from '@/types/pricing'

/** A blank field means "not entered", which is different from zero. */
const optionalDecimal = (message: string) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || (/^\d*\.?\d+$/.test(value) && Number(value) >= 0), message)

const optionalWhole = (message: string, { min = 0 }: { min?: number } = {}) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || (/^\d+$/.test(value) && Number(value) >= min), message)

const schema = z.object({
  print_time_minutes: optionalWhole('Enter a whole number of minutes, or leave it blank'),
  prints_per_plate: optionalWhole(
    'Enter how many parts share a plate — at least one, since per-plate work is divided across them',
    { min: 1 },
  ),
  waste_grams: optionalDecimal('Enter a non-negative weight, or leave it blank'),
  expected_yield: z
    .string()
    .trim()
    .refine(
      (value) => value === '' || (/^\d*\.?\d+$/.test(value) && Number(value) > 0 && Number(value) <= 1),
      'Enter a success rate above 0 and up to 1 — 0.92 means 92% of starts reach a sellable part',
    ),
  failure_mode: z.enum(['per_part', 'per_plate']),
  labor_hours_per_plate: optionalDecimal('Enter non-negative hours, or leave it blank'),
  labor_hours_per_item: optionalDecimal('Enter non-negative hours, or leave it blank'),
  finishing_hours_per_item: optionalDecimal('Enter non-negative hours, or leave it blank'),
  packing_hours_per_item: optionalDecimal('Enter non-negative hours, or leave it blank'),
})

type FormValues = z.infer<typeof schema>

interface ModelCostProfileFormProps {
  modelId: string
  modelName?: string
  /** False for a viewer: they may read every figure but change none (FR-007c). */
  canEdit?: boolean
  /** Called after a successful save, for a dialog that wants to close itself. */
  onSaved?: () => void
}

export function ModelCostProfileForm({
  modelId,
  modelName,
  canEdit = true,
  onSaved,
}: ModelCostProfileFormProps) {
  const { profile, isLoading, error } = useModelCostProfile(modelId)
  const { updateCostProfileAsync, isUpdating, error: saveError } =
    useUpdateModelCostProfile(modelId)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      print_time_minutes: '',
      prints_per_plate: '',
      waste_grams: '',
      expected_yield: '',
      failure_mode: 'per_part',
      labor_hours_per_plate: '',
      labor_hours_per_item: '',
      finishing_hours_per_item: '',
      packing_hours_per_item: '',
    },
  })

  useEffect(() => {
    if (profile && !form.formState.isDirty) {
      form.reset({
        print_time_minutes:
          profile.print_time_minutes === null ? '' : String(profile.print_time_minutes),
        prints_per_plate: String(profile.prints_per_plate),
        waste_grams: profile.waste_grams ?? '',
        expected_yield: profile.expected_yield ?? '',
        failure_mode: profile.failure_mode,
        labor_hours_per_plate: profile.labor_hours_per_plate ?? '',
        labor_hours_per_item: profile.labor_hours_per_item ?? '',
        finishing_hours_per_item: profile.finishing_hours_per_item ?? '',
        packing_hours_per_item: profile.packing_hours_per_item ?? '',
      })
    }
  }, [profile, form])

  const originOf = (fieldName: string): CostProfileFieldOrigin | undefined =>
    profile?.origins.find((entry) => entry.field_name === fieldName)

  const isReadOnly = (fieldName: string) => {
    if (!canEdit) return true
    const origin = originOf(fieldName)
    // An observed figure is refreshed from its source and never typed over
    // (FR-004). The server refuses it either way; disabling the input is so the
    // operator does not type into a field that cannot accept it.
    return origin ? !origin.editable : false
  }

  const onSubmit = async (values: FormValues) => {
    // Only what the operator filled in is sent. A blank field must not erase a
    // figure recorded earlier, and the mode is always sent because a select
    // always holds one.
    const changes: ModelCostProfileUpdate = { failure_mode: values.failure_mode }
    if (values.print_time_minutes !== '') {
      changes.print_time_minutes = Number(values.print_time_minutes)
    }
    if (values.prints_per_plate !== '') {
      changes.prints_per_plate = Number(values.prints_per_plate)
    }
    for (const field of [
      'waste_grams',
      'expected_yield',
      'labor_hours_per_plate',
      'labor_hours_per_item',
      'finishing_hours_per_item',
      'packing_hours_per_item',
    ] as const) {
      if (values[field] !== '') changes[field] = values[field]
    }

    await updateCostProfileAsync(changes)
    form.reset(values)
    onSaved?.()
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>Failed to load this item&apos;s cost profile</AlertDescription>
      </Alert>
    )
  }

  /** The label, with the origin of the figure beside it. */
  const labelWithOrigin = (text: string, fieldName: string) => {
    const origin = originOf(fieldName)
    return (
      <div className="flex items-center gap-2">
        <span>{text}</span>
        {origin && (
          <ProvenanceBadge
            source={origin.source}
            asOf={origin.as_of}
            isStale={origin.is_stale}
            isDefault={!origin.as_of}
          />
        )}
      </div>
    )
  }

  const incomplete = profile?.incomplete_reasons ?? []

  return (
    <Card data-testid="model-cost-profile-form">
      <CardHeader>
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-5 w-5" />
          <CardTitle>Cost profile{modelName ? ` — ${modelName}` : ''}</CardTitle>
        </div>
        <CardDescription>
          The measurements that decide what printing this costs: how long a plate takes, how
          much filament is purged before the part, how often a print fails, and the minutes of
          handling, finishing and packing it takes. These are measurements, so any member can
          record them.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {incomplete.length > 0 && (
          <Alert data-testid="profile-incomplete">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>This item is not fully costed yet</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4">
                {incomplete.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {saveError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Not saved</AlertTitle>
            <AlertDescription>{saveError.message}</AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="print_time_minutes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Plate print time', 'print_time_minutes')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="numeric"
                      placeholder="570"
                      disabled={isReadOnly('print_time_minutes')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Minutes for one whole plate, as the slicer reports it. Without it the machine
                    and overhead lines cannot be costed at all.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="prints_per_plate"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Parts per plate', 'prints_per_plate')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="numeric"
                      placeholder="1"
                      disabled={isReadOnly('prints_per_plate')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    How many of this part one plate carries. Plate time, purge and plate
                    preparation are all divided across it.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="waste_grams"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Purge and priming (g)', 'waste_grams')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="3.00"
                      disabled={isReadOnly('waste_grams')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Filament consumed per plate that never ends up in a part — purge, priming and
                    colour changes. Costed as its own line, not folded into the part weight.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Separator />

            <FormField
              control={form.control}
              name="expected_yield"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Success rate', 'expected_yield')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.92"
                      disabled={isReadOnly('expected_yield')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    The share of starts that reach a sellable part, as a fraction: 0.92 is 92%.
                    It raises the cost of the work exposed to failure and leaves packaging and
                    packing alone — those happen on a part already known good.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="failure_mode"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>How failures happen</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={!canEdit}
                  >
                    <FormControl>
                      <SelectTrigger data-testid="failure-mode-select">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="per_part">
                        Parts fail on their own (per part)
                      </SelectItem>
                      <SelectItem value="per_plate">
                        One failure ruins the plate (per plate)
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    The same success rate means different things here. With parts failing on
                    their own, one bad part costs you one part. With a plate at stake, a single
                    failure costs the whole plate — so a plate of four is markedly dearer at the
                    same success rate. Changing this stops your recorded success rate counting
                    as evidence for the new mode, because it was never measured under it.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Separator />

            <FormField
              control={form.control}
              name="labor_hours_per_plate"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {labelWithOrigin('Plate setup (hours)', 'labor_hours_per_plate')}
                  </FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.250"
                      disabled={isReadOnly('labor_hours_per_plate')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Work a plate needs once however many parts are on it — slicing, loading,
                    clearing the bed. Divided across the plate&apos;s output.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="labor_hours_per_item"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {labelWithOrigin('Handling per part (hours)', 'labor_hours_per_item')}
                  </FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.050"
                      disabled={isReadOnly('labor_hours_per_item')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Work every part needs individually. Never divided across a plate.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="finishing_hours_per_item"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {labelWithOrigin('Finishing per part (hours)', 'finishing_hours_per_item')}
                  </FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.100"
                      disabled={isReadOnly('finishing_hours_per_item')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Sanding, supports, painting. Charged at your finishing rate, which can differ
                    from the handling rate.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="packing_hours_per_item"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {labelWithOrigin('Packing per part (hours)', 'packing_hours_per_item')}
                  </FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.083"
                      disabled={isReadOnly('packing_hours_per_item')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Boxing a finished part. Never raised by the failure rate — a part being
                    packed has already succeeded.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {canEdit && (
              <Button type="submit" disabled={isUpdating}>
                {isUpdating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save cost profile
              </Button>
            )}
          </form>
        </Form>
      </CardContent>
    </Card>
  )
}
