/**
 * ShippingProfilesPanel — the postage the operator pays, by zone and weight (T245).
 *
 * Every margin deducts postage from these profiles (FR-024), and the hooks to
 * manage them had no screen, so the figures could be entered only through the
 * API. A change to the postage, the zone or a bracket is a repricing: the API
 * closes the current profile and opens a successor dated from today, so orders
 * already placed keep the postage they were costed at (FR-003). The screen
 * says so beside the save, because "edit" would otherwise read as rewriting
 * history.
 *
 * Setting postage is monetary policy (FR-007a): a viewer or member reads the
 * table, and only an admin or owner is offered the controls.
 *
 * Amounts are the decimal strings the API sent and the operator typed — never
 * parsed to a JavaScript number (Constitution IV).
 */

import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { AlertCircle, Edit, Loader2, Plus, Trash2, Truck } from 'lucide-react'

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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  useCreateShippingProfile,
  useDeleteShippingProfile,
  useShippingProfiles,
  useUpdateShippingProfile,
} from '@/hooks/useFeeRules'
import { useCurrency } from '@/hooks/useCurrency'
import { formatMoney } from '@/lib/money'
import type { ShippingProfile, ShippingProfileCreate } from '@/types/pricing'

const amount = /^\d+(\.\d{1,2})?$/
const grams = /^\d+(\.\d+)?$/
// A positive length (or divisor) to at most one decimal place.
const mm = /^(?!0+(\.0)?$)\d+(\.\d)?$/
const MM_MESSAGE = 'Enter a size in mm, to at most one decimal place'

const schema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(100),
  destination_zone: z.string().trim().min(1, 'Zone is required').max(50),
  weight_bracket_min_grams: z
    .string()
    .trim()
    .refine((v) => v === '' || grams.test(v), 'Enter a weight in grams'),
  weight_bracket_max_grams: z
    .string()
    .trim()
    .refine((v) => v === '' || grams.test(v), 'Enter a weight in grams, or leave it open'),
  postage_cost: z.string().trim().regex(amount, 'Enter an amount, e.g. 3.85'),
  carrier: z.string().trim().max(50),
  max_length_mm: z.string().trim().refine((v) => v === '' || mm.test(v), MM_MESSAGE),
  max_width_mm: z.string().trim().refine((v) => v === '' || mm.test(v), MM_MESSAGE),
  max_height_mm: z.string().trim().refine((v) => v === '' || mm.test(v), MM_MESSAGE),
  volumetric_divisor: z
    .string()
    .trim()
    .refine((v) => v === '' || mm.test(v), 'Enter the divisor, e.g. 5000, or leave it blank'),
}).refine(
  // A size class is all three limits or none (research D9).
  (v) => {
    const given = [v.max_length_mm, v.max_width_mm, v.max_height_mm].filter((x) => x !== '')
    return given.length === 0 || given.length === 3
  },
  { message: 'Give all three size limits, or none', path: ['max_height_mm'] },
)

type FormValues = z.infer<typeof schema>

const EMPTY: FormValues = {
  name: '',
  destination_zone: '',
  weight_bracket_min_grams: '',
  weight_bracket_max_grams: '',
  postage_cost: '',
  carrier: '',
  max_length_mm: '',
  max_width_mm: '',
  max_height_mm: '',
  volumetric_divisor: '',
}

function sizeLabel(profile: ShippingProfile): string | null {
  if (!profile.max_length_mm || !profile.max_width_mm || !profile.max_height_mm) return null
  return `≤ ${profile.max_length_mm} × ${profile.max_width_mm} × ${profile.max_height_mm} mm`
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function bracketLabel(profile: ShippingProfile): string {
  const min = profile.weight_bracket_min_grams ?? '0'
  return profile.weight_bracket_max_grams == null
    ? `${min} g and over`
    : `${min}–${profile.weight_bracket_max_grams} g`
}

interface ShippingProfilesPanelProps {
  /** False below admin: postage is monetary policy (FR-007a). */
  canEdit?: boolean
}

export function ShippingProfilesPanel({ canEdit = false }: ShippingProfilesPanelProps) {
  const { currency } = useCurrency()
  const { profiles, isLoading, error } = useShippingProfiles()
  const create = useCreateShippingProfile()
  const update = useUpdateShippingProfile()
  const remove = useDeleteShippingProfile()

  // null: no form open; 'new': adding; otherwise the profile being changed.
  const [editing, setEditing] = useState<ShippingProfile | 'new' | null>(null)

  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: EMPTY })

  const open = (profile: ShippingProfile | 'new') => {
    setEditing(profile)
    form.reset(
      profile === 'new'
        ? EMPTY
        : {
            name: profile.name,
            destination_zone: profile.destination_zone,
            weight_bracket_min_grams: profile.weight_bracket_min_grams ?? '',
            weight_bracket_max_grams: profile.weight_bracket_max_grams ?? '',
            postage_cost: profile.postage_cost,
            carrier: profile.carrier ?? '',
            max_length_mm: profile.max_length_mm ?? '',
            max_width_mm: profile.max_width_mm ?? '',
            max_height_mm: profile.max_height_mm ?? '',
            volumetric_divisor: profile.volumetric_divisor ?? '',
          },
    )
  }

  const onSubmit = async (values: FormValues) => {
    const body: ShippingProfileCreate = {
      name: values.name,
      destination_zone: values.destination_zone,
      weight_bracket_min_grams: values.weight_bracket_min_grams || '0',
      weight_bracket_max_grams: values.weight_bracket_max_grams || null,
      postage_cost: values.postage_cost,
      carrier: values.carrier || null,
      effective_from: today(),
      max_length_mm: values.max_length_mm || null,
      max_width_mm: values.max_width_mm || null,
      max_height_mm: values.max_height_mm || null,
      volumetric_divisor: values.volumetric_divisor || null,
    }
    if (editing === 'new') {
      await create.mutateAsync(body)
    } else if (editing) {
      // effective_from is the successor's opening date when this reprices;
      // the API ignores it for a name or carrier correction.
      await update.mutateAsync({ profileId: editing.id, data: body })
    }
    setEditing(null)
  }

  const saveError = create.error ?? update.error ?? remove.error
  const saving = create.isPending || update.isPending

  return (
    <Card data-testid="shipping-profiles-panel">
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Truck className="h-5 w-5" />
            <CardTitle>Postage</CardTitle>
          </div>
          {canEdit && editing === null && (
            <Button size="sm" onClick={() => open('new')}>
              <Plus className="mr-1 h-4 w-4" />
              Add postage
            </Button>
          )}
        </div>
        <CardDescription>
          What you pay to post a parcel, by destination zone and weight. Every margin deducts it,
          and shows it against the shipping the customer was charged.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {saveError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Not saved</AlertTitle>
            <AlertDescription>{saveError.message}</AlertDescription>
          </Alert>
        )}

        {editing !== null && (
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className="grid gap-3 rounded-md border p-4 sm:grid-cols-2"
              data-testid="shipping-profile-form"
            >
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="UK small parcel" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="destination_zone"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Zone</FormLabel>
                    <FormControl>
                      <Input placeholder="UK" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="weight_bracket_min_grams"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>From (g)</FormLabel>
                    <FormControl>
                      <Input inputMode="decimal" placeholder="0" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="weight_bracket_max_grams"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Up to (g)</FormLabel>
                    <FormControl>
                      <Input inputMode="decimal" placeholder="Open" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="postage_cost"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Postage paid</FormLabel>
                    <FormControl>
                      <Input inputMode="decimal" placeholder="3.85" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="carrier"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Carrier</FormLabel>
                    <FormControl>
                      <Input placeholder="Royal Mail" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <fieldset className="grid gap-3 sm:col-span-2 sm:grid-cols-3">
                <legend className="text-sm font-medium mb-1">Size limits (mm)</legend>
                {(
                  [
                    ['max_length_mm', 'Max length (mm)', '353'],
                    ['max_width_mm', 'Max width (mm)', '250'],
                    ['max_height_mm', 'Max height (mm)', '25'],
                  ] as const
                ).map(([name, label, placeholder]) => (
                  <FormField
                    key={name}
                    control={form.control}
                    name={name}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>{label}</FormLabel>
                        <FormControl>
                          <Input inputMode="decimal" placeholder={placeholder} {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                ))}
              </fieldset>
              <FormField
                control={form.control}
                name="volumetric_divisor"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Volumetric divisor</FormLabel>
                    <FormControl>
                      <Input inputMode="decimal" placeholder="None" {...field} />
                    </FormControl>
                    <FormDescription>
                      cm³ per kg, e.g. 5000. Leave blank if the carrier charges actual weight.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormDescription className="sm:col-span-2" data-testid="shipping-supersede-note">
                {editing === 'new'
                  ? 'Applies from today.'
                  : 'A new postage, zone or weight takes effect from today; orders already placed keep the postage they were costed at. A name or carrier is corrected in place.'}
              </FormDescription>
              <div className="flex gap-2 sm:col-span-2">
                <Button type="submit" disabled={saving}>
                  {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save postage
                </Button>
                <Button type="button" variant="ghost" onClick={() => setEditing(null)}>
                  Cancel
                </Button>
              </div>
            </form>
          </Form>
        )}

        {isLoading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : error ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>Failed to load postage</AlertDescription>
          </Alert>
        ) : profiles.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="shipping-profiles-empty">
            No postage recorded, so margins cannot deduct what posting an order costs.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Zone</TableHead>
                <TableHead>Weight</TableHead>
                <TableHead className="text-right">Postage</TableHead>
                <TableHead>Carrier</TableHead>
                <TableHead>In force</TableHead>
                <TableHead className="w-[90px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {profiles.map((profile) => (
                <TableRow key={profile.id} data-testid={`shipping-profile-${profile.id}`}>
                  <TableCell className="font-medium">{profile.name}</TableCell>
                  <TableCell>{profile.destination_zone}</TableCell>
                  <TableCell className="tabular-nums">
                    {bracketLabel(profile)}
                    {sizeLabel(profile) && (
                      <div className="text-xs text-muted-foreground">{sizeLabel(profile)}</div>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(profile.postage_cost, currency.symbol)}
                  </TableCell>
                  <TableCell>{profile.carrier ?? '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {profile.effective_to
                      ? `${profile.effective_from} to ${profile.effective_to}`
                      : `from ${profile.effective_from}`}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Change ${profile.name}`}
                        disabled={!canEdit || profile.effective_to != null}
                        onClick={() => open(profile)}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Stop using ${profile.name}`}
                        disabled={!canEdit || remove.isPending || profile.effective_to != null}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Stop using "${profile.name}" from today? Orders already placed keep their postage.`,
                            )
                          ) {
                            remove.mutate(profile.id)
                          }
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
