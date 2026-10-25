/**
 * PricingPolicySettings — the levers behind every cost on every screen.
 *
 * Two things this screen must get across, because the defect it closes was
 * exactly their absence:
 *
 * * **These figures are decisions, not guesses** (FR-002). They are the
 *   operator's, nothing overwrites them, and changing one writes a new
 *   effective period rather than editing the old one — so the rate a past
 *   order was costed at stays readable (FR-003).
 * * **A fallback is labelled as one.** A tenant whose policy has not been
 *   written yet reads `origin: 'legacy_settings'`; presenting that as
 *   configured would repeat the original mistake, where a rate nobody chose
 *   drove every figure.
 */

import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { AlertCircle, Info, Loader2, SlidersHorizontal } from 'lucide-react'

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
import { usePricingPolicy, useUpdatePricingPolicy } from '@/hooks/usePricing'
import { compareMoney, formatMoney } from '@/lib/money'
import { ProvenanceBadge } from '@/components/pricing/ProvenanceBadge'
import type { PricingPolicyUpdate } from '@/types/pricing'

const nonNegative = (message: string) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || (/^\d*\.?\d+$/.test(value) && Number(value) >= 0), message)

const schema = z
  .object({
    print_labor_rate: nonNegative('Enter a non-negative hourly rate'),
    finishing_labor_rate: nonNegative('Enter a non-negative hourly rate'),
    default_machine_rate_per_hour: nonNegative('Enter a non-negative hourly rate, or blank'),
    overhead_method: z.enum(['per_machine_hour', 'percentage']),
    overhead_monthly_pool: nonNegative('Enter a non-negative amount, or blank'),
    expected_monthly_machine_hours: nonNegative('Enter a non-negative number, or blank'),
    electricity_rate_per_kwh: nonNegative('Enter a non-negative rate, or blank'),
    overhead_percentage: nonNegative('Enter a non-negative percentage'),
    margin_basis: z.enum(['customer_total', 'item_price', 'net_revenue']),
  })
  .refine(
    (values) =>
      values.overhead_method !== 'per_machine_hour' ||
      (values.expected_monthly_machine_hours !== '' &&
        Number(values.expected_monthly_machine_hours) > 0),
    {
      path: ['expected_monthly_machine_hours'],
      message:
        'Absorbing overhead per machine-hour needs an expected capacity above zero — a capacity of zero is a misconfiguration, not a divisor',
    },
  )

type FormValues = z.infer<typeof schema>

const MARGIN_BASIS_LABEL: Record<FormValues['margin_basis'], string> = {
  customer_total: 'Everything the customer paid, shipping included',
  item_price: 'The item price alone',
  net_revenue: 'What was left after fees and refunds',
}

interface PricingPolicySettingsProps {
  /** False for a member or viewer: they may read the policy but not set it. */
  canEdit?: boolean
}

export function PricingPolicySettings({ canEdit = true }: PricingPolicySettingsProps) {
  const { policy, isLoading, error } = usePricingPolicy()
  const { updatePolicy, isUpdating, error: saveError } = useUpdatePricingPolicy()

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      print_labor_rate: '',
      finishing_labor_rate: '',
      default_machine_rate_per_hour: '',
      overhead_method: 'percentage',
      overhead_monthly_pool: '',
      expected_monthly_machine_hours: '',
      electricity_rate_per_kwh: '',
      overhead_percentage: '',
      margin_basis: 'customer_total',
    },
  })

  useEffect(() => {
    if (policy && !form.formState.isDirty) {
      form.reset({
        print_labor_rate: policy.print_labor_rate,
        finishing_labor_rate: policy.finishing_labor_rate,
        default_machine_rate_per_hour: policy.default_machine_rate_per_hour ?? '',
        overhead_method: policy.overhead_method,
        overhead_monthly_pool: policy.overhead_monthly_pool ?? '',
        expected_monthly_machine_hours: policy.expected_monthly_machine_hours ?? '',
        electricity_rate_per_kwh: policy.electricity_rate_per_kwh ?? '',
        overhead_percentage: policy.overhead_percentage,
        margin_basis: policy.margin_basis,
      })
    }
  }, [policy, form])

  // `useWatch` rather than `form.watch`: the value is set by `form.reset`
  // once the policy loads, and only a subscription re-renders this branch.
  const method = useWatch({ control: form.control, name: 'overhead_method' })

  // Only the levers the administrator moved are sent (T260). The server
  // records each lever it is sent as a decision, so re-sending an unchanged
  // default would relabel a figure nobody chose as policy.
  const DECIMAL_LEVERS = [
    'print_labor_rate',
    'finishing_labor_rate',
    'default_machine_rate_per_hour',
    'overhead_monthly_pool',
    'expected_monthly_machine_hours',
    'electricity_rate_per_kwh',
    'overhead_percentage',
  ] as const

  const onSubmit = (values: FormValues) => {
    const changes: PricingPolicyUpdate = {}
    for (const lever of DECIMAL_LEVERS) {
      const value = values[lever]
      if (value === '') continue
      const current = policy?.[lever] ?? null
      if (current === null || compareMoney(value, current) !== 0) changes[lever] = value
    }
    if (values.overhead_method !== policy?.overhead_method) {
      changes.overhead_method = values.overhead_method
    }
    if (values.margin_basis !== policy?.margin_basis) changes.margin_basis = values.margin_basis
    if (Object.keys(changes).length === 0) return
    updatePolicy(changes)
  }

  /** A lever's label with its own origin beside it (T260). */
  const labelWithOrigin = (text: string, lever: string) => {
    const origin = policy?.levers?.[lever]
    return (
      <span className="flex items-center gap-2">
        <span>{text}</span>
        {origin && policy?.origin === 'policy_row' && (
          <ProvenanceBadge
            source={origin.source}
            asOf={origin.as_of}
            isStale={false}
            isDefault={!origin.as_of}
          />
        )}
      </span>
    )
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
        <AlertDescription>Failed to load your pricing policy</AlertDescription>
      </Alert>
    )
  }

  return (
    <Card data-testid="pricing-policy-settings">
      <CardHeader>
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-5 w-5" />
          <CardTitle>Pricing policy</CardTitle>
        </div>
        <CardDescription>
          The rates and methods behind every cost and margin in Batchivo. Nothing here is
          changed automatically, and changing a figure starts a new period rather than
          rewriting the old one — so a past order keeps the figures it was costed at.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {policy?.origin === 'legacy_settings' && (
          <Alert data-testid="legacy-origin-notice">
            <Info className="h-4 w-4" />
            <AlertTitle>These are fallback figures</AlertTitle>
            <AlertDescription>
              Your policy has not been saved yet, so these come from your old settings. Save
              them to make them yours — nothing below changes until you do.
            </AlertDescription>
          </Alert>
        )}

        {policy?.origin === 'policy_row' && policy.source === 'assumed' && (
          <Alert data-testid="assumed-policy-notice">
            <Info className="h-4 w-4" />
            <AlertTitle>Nobody has set these figures yet</AlertTitle>
            <AlertDescription>
              They are the defaults your workspace started with, and every cost built from
              them is labelled as an assumption until you save your own.
            </AlertDescription>
          </Alert>
        )}

        {policy?.effective_from && policy.origin === 'policy_row' && (
          <p className="text-sm text-muted-foreground" data-testid="effective-from">
            In effect since {policy.effective_from}
            {policy.set_by_role ? `, set by ${policy.set_by_role}` : ''}.
          </p>
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
              name="print_labor_rate"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Print handling rate (per hour)', 'print_labor_rate')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="25.00"
                      disabled={!canEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    What your time is worth starting prints, clearing plates and handling parts.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="finishing_labor_rate"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Finishing rate (per hour)', 'finishing_labor_rate')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="25.00"
                      disabled={!canEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Sanding, painting and assembly can be worth a different rate from handling.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Separator />

            <FormField
              control={form.control}
              name="overhead_method"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('How overhead reaches a unit', 'overhead_method')}</FormLabel>
                  <Select
                    onValueChange={(value) => {
                      // Radix emits '' on mount when the value matches no
                      // mounted item; there is no empty option here, so an
                      // empty value is never a choice the operator made.
                      if (value) field.onChange(value)
                    }}
                    value={field.value}
                    disabled={!canEdit}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="per_machine_hour">
                        Spread over machine-hours
                      </SelectItem>
                      <SelectItem value="percentage">
                        A percentage of material and labor
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Machine-hours is the more honest method: a long print absorbs more of your
                    rent than a short one. The percentage method is kept because it is what
                    your existing costs were built from.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {method === 'percentage' && (
              <FormField
                control={form.control}
                name="overhead_percentage"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{labelWithOrigin('Overhead percentage', 'overhead_percentage')}</FormLabel>
                    <FormControl>
                      <Input inputMode="decimal" placeholder="15" disabled={!canEdit} {...field} />
                    </FormControl>
                    <FormDescription>
                      Added on top of material and labor for every item that carries no
                      percentage of its own.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {method === 'per_machine_hour' && (
              <>
                <FormField
                  control={form.control}
                  name="overhead_monthly_pool"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{labelWithOrigin('Monthly overhead', 'overhead_monthly_pool')}</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="decimal"
                          placeholder="180.00"
                          disabled={!canEdit}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        Rent, software, insurance — what the workshop costs you each month
                        whether or not a printer runs.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="expected_monthly_machine_hours"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{labelWithOrigin('Expected machine-hours a month', 'expected_monthly_machine_hours')}</FormLabel>
                      <FormControl>
                        <Input
                          inputMode="decimal"
                          placeholder="600"
                          disabled={!canEdit}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        The hours you expect your machines to actually print.
                        {policy?.overhead_rate_per_machine_hour !== null &&
                          policy?.overhead_rate_per_machine_hour !== undefined &&
                          ` Currently absorbing ${formatMoney(
                            policy.overhead_rate_per_machine_hour,
                          )} per machine-hour.`}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </>
            )}

            <FormField
              control={form.control}
              name="default_machine_rate_per_hour"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('Fallback machine rate (per hour)', 'default_machine_rate_per_hour')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.2324"
                      disabled={!canEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Used when an item is not planned on a particular printer. Leave blank and
                    such an item is reported as incompletely costed instead of being costed at
                    nothing.
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
                  <FormLabel>{labelWithOrigin('Electricity rate (per kWh)', 'electricity_rate_per_kwh')}</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="decimal"
                      placeholder="0.1300"
                      disabled={!canEdit}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Used by any printer that carries no rate of its own.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Separator />

            <FormField
              control={form.control}
              name="margin_basis"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{labelWithOrigin('What a margin percentage is taken over', 'margin_basis')}</FormLabel>
                  <Select
                    onValueChange={(value) => {
                      // Radix emits '' on mount when the value matches no
                      // mounted item; there is no empty option here, so an
                      // empty value is never a choice the operator made.
                      if (value) field.onChange(value)
                    }}
                    value={field.value}
                    disabled={!canEdit}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {(
                        Object.keys(MARGIN_BASIS_LABEL) as Array<FormValues['margin_basis']>
                      ).map((basis) => (
                        <SelectItem key={basis} value={basis}>
                          {MARGIN_BASIS_LABEL[basis]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    This changes the percentage only, never the profit in money. Whichever you
                    pick is named beside every margin figure.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {canEdit ? (
              <div className="flex items-center gap-4 pt-2">
                <Button type="submit" disabled={isUpdating || !form.formState.isDirty}>
                  {isUpdating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save pricing policy
                </Button>
              </div>
            ) : (
              <p className="pt-2 text-sm text-muted-foreground" data-testid="read-only-notice">
                Only an admin or owner can change your pricing policy.
              </p>
            )}
          </form>
        </Form>
      </CardContent>
    </Card>
  )
}
