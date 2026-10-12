/**
 * PrinterCostPolicyForm — what this machine costs per hour it is occupied.
 *
 * The rate is derived, never typed: depreciation over expected life, plus a
 * maintenance reserve over the same life, plus measured draw at the operator's
 * electricity rate (FR-010). The form therefore shows the parts it is made of
 * beside the total, so the figure can be checked without being recomputed
 * (FR-018), and names what is still missing rather than implying a complete
 * rate (FR-019).
 *
 * Every field is optional on purpose. A machine whose policy nobody has
 * entered yields *no* rate and marks the item incompletely costed; a zero
 * would read like a real figure and make a 40-hour print look free.
 */

import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { AlertCircle, Gauge, Loader2 } from 'lucide-react'

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
import { Separator } from '@/components/ui/separator'
import { usePrinterCostPolicy, useUpdatePrinterCostPolicy } from '@/hooks/usePricing'
import { formatMoney } from '@/lib/money'
import type { PrinterCostPolicyUpdate } from '@/types/pricing'

/** Human wording for each input the derived rate can be missing. */
const MISSING_LABEL: Record<string, string> = {
  purchase_price: 'what the machine cost to buy',
  expected_lifetime_hours: 'how many printing hours you expect from it',
  maintenance_reserve_total: 'what you expect to spend on parts over its life',
  measured_watts: 'its measured draw while printing',
  electricity_rate_per_kwh: 'your electricity rate',
}

/** Human wording for each part of the derived rate. */
const COMPONENT_LABEL: Record<string, string> = {
  depreciation_per_hour: 'Depreciation',
  maintenance_per_hour: 'Maintenance reserve',
  power_per_hour: 'Power',
}

/** A blank field means "not entered", which is different from zero. */
const optionalDecimal = (message: string) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || (/^\d*\.?\d+$/.test(value) && Number(value) >= 0), message)

const schema = z.object({
  purchase_price: optionalDecimal('Enter a non-negative amount, or leave it blank'),
  expected_lifetime_hours: z
    .string()
    .trim()
    .refine(
      (value) => value === '' || (/^\d+$/.test(value) && Number(value) > 0),
      'Enter a whole number of hours above zero — depreciation over zero hours is not a rate',
    ),
  maintenance_reserve_total: optionalDecimal('Enter a non-negative amount, or leave it blank'),
  measured_watts: optionalDecimal('Enter a non-negative wattage, or leave it blank'),
  electricity_rate_per_kwh: optionalDecimal('Enter a non-negative rate, or leave it blank'),
})

type FormValues = z.infer<typeof schema>

interface PrinterCostPolicyFormProps {
  printerId: string
  printerName?: string
  /** False for a member or viewer: they may read the rate but not set it. */
  canEdit?: boolean
}

export function PrinterCostPolicyForm({
  printerId,
  printerName,
  canEdit = true,
}: PrinterCostPolicyFormProps) {
  const { costPolicy, isLoading, error } = usePrinterCostPolicy(printerId)
  const { updateCostPolicy, isUpdating, error: saveError } = useUpdatePrinterCostPolicy(printerId)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      purchase_price: '',
      expected_lifetime_hours: '',
      maintenance_reserve_total: '',
      measured_watts: '',
      electricity_rate_per_kwh: '',
    },
  })

  useEffect(() => {
    if (costPolicy && !form.formState.isDirty) {
      form.reset({
        purchase_price: costPolicy.purchase_price ?? '',
        expected_lifetime_hours:
          costPolicy.expected_lifetime_hours === null
            ? ''
            : String(costPolicy.expected_lifetime_hours),
        maintenance_reserve_total: costPolicy.maintenance_reserve_total ?? '',
        measured_watts: costPolicy.measured_watts ?? '',
        electricity_rate_per_kwh: costPolicy.electricity_rate_per_kwh ?? '',
      })
    }
  }, [costPolicy, form])

  const onSubmit = (values: FormValues) => {
    // Only the fields the operator filled in are sent. A blank field must not
    // erase a figure entered earlier.
    const changes: PrinterCostPolicyUpdate = {}
    if (values.purchase_price !== '') changes.purchase_price = values.purchase_price
    if (values.expected_lifetime_hours !== '') {
      changes.expected_lifetime_hours = Number(values.expected_lifetime_hours)
    }
    if (values.maintenance_reserve_total !== '') {
      changes.maintenance_reserve_total = values.maintenance_reserve_total
    }
    if (values.measured_watts !== '') changes.measured_watts = values.measured_watts
    if (values.electricity_rate_per_kwh !== '') {
      changes.electricity_rate_per_kwh = values.electricity_rate_per_kwh
    }
    updateCostPolicy(changes)
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
        <AlertDescription>Failed to load this printer&apos;s cost policy</AlertDescription>
      </Alert>
    )
  }

  const components = Object.entries(costPolicy?.components ?? {})
  const missing = costPolicy?.missing ?? []

  return (
    <Card data-testid="printer-cost-policy-form">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Gauge className="h-5 w-5" />
          <CardTitle>Machine cost{printerName ? ` — ${printerName}` : ''}</CardTitle>
        </div>
        <CardDescription>
          What an hour on this machine costs you, worked out from what you paid for it, what
          you expect to spend keeping it running, and what it draws while printing.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="rounded-md bg-muted p-3" data-testid="derived-rate">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-medium">Cost per printing hour</span>
            <span className="text-lg tabular-nums">
              {costPolicy?.machine_rate_per_hour === null ? (
                <span className="text-muted-foreground" data-testid="rate-unknown">
                  not yet known
                </span>
              ) : (
                formatMoney(costPolicy?.machine_rate_per_hour)
              )}
            </span>
          </div>

          {components.length > 0 && (
            <>
              <Separator className="my-2" />
              <dl className="space-y-1 text-sm">
                {components.map(([key, amount]) => (
                  <div key={key} className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">{COMPONENT_LABEL[key] ?? key}</dt>
                    <dd className="tabular-nums">{formatMoney(amount)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}

          {missing.length > 0 && (
            <p className="mt-2 text-sm text-muted-foreground" data-testid="missing-inputs">
              Still needed before this rate is complete:{' '}
              {missing.map((key) => MISSING_LABEL[key] ?? key).join(', ')}.
            </p>
          )}
        </div>

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
              name="purchase_price"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Purchase price</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="1100.00"
                      disabled={!canEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Everything it cost to get the machine printing, not just the sticker price.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="expected_lifetime_hours"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Expected printing hours</FormLabel>
                  <FormControl>
                    <Input inputMode="numeric" placeholder="6000" disabled={!canEdit} {...field} />
                  </FormControl>
                  <FormDescription>
                    How many hours of printing you expect from it in total. This is the
                    denominator of both depreciation and the maintenance reserve.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="maintenance_reserve_total"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Maintenance reserve</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="220.00"
                      disabled={!canEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Nozzles, belts, plates and AMS parts you expect to buy over its whole life.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="measured_watts"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Measured draw while printing (watts)</FormLabel>
                  <FormControl>
                    <Input inputMode="decimal" placeholder="95" disabled={!canEdit} {...field} />
                  </FormControl>
                  <FormDescription>
                    Measured at the wall, not the figure on the nameplate — they differ by more
                    than you would expect.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="electricity_rate_per_kwh"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Electricity rate (per kWh)</FormLabel>
                  <FormControl>
                    <Input inputMode="decimal" placeholder="0.1300" disabled={!canEdit} {...field} />
                  </FormControl>
                  <FormDescription>
                    Leave blank to use the rate from your pricing settings.
                    {costPolicy?.electricity_rate_per_kwh === null &&
                      costPolicy?.effective_electricity_rate_per_kwh !== null &&
                      ` Currently using ${formatMoney(
                        costPolicy?.effective_electricity_rate_per_kwh,
                      )} from there.`}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {canEdit ? (
              <div className="flex items-center gap-4 pt-2">
                <Button type="submit" disabled={isUpdating || !form.formState.isDirty}>
                  {isUpdating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save machine cost
                </Button>
              </div>
            ) : (
              <p className="pt-2 text-sm text-muted-foreground" data-testid="read-only-notice">
                Only an admin or owner can change what a machine costs.
              </p>
            )}
          </form>
        </Form>
      </CardContent>
    </Card>
  )
}
