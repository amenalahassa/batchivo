/**
 * FilamentPurchaseForm — record what a batch of filament actually cost.
 *
 * The point of recording the purchase rather than a per-gram figure is that
 * inbound shipping arrives once for the whole order and has to be spread
 * across it by weight (FR-008a, FR-008b). That spreading is what the operator
 * would otherwise do by hand on the back of an envelope, and what nobody can
 * explain six months later.
 *
 * So the allocation is shown, per spool, with the derivation it came from
 * (FR-008f) — and the usable weight is shown too, because a 1 kg spool with
 * 25 g that can never be printed holds 975 printable grams and costing it at
 * 1000 understates every part made from it (FR-008d).
 */

import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { AlertCircle, Info, Loader2, Package } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
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
import { Textarea } from '@/components/ui/textarea'
import { useFilamentPurchase, useSaveFilamentPurchase } from '@/hooks/usePricing'
import { formatMoney } from '@/lib/money'
import type { FilamentPurchase, SpoolLandedCost } from '@/types/pricing'
import { useAuth } from '@/contexts/AuthContext'
import { canEditOperationalFigures } from '@/lib/pricing/permissions'

const nonNegative = (message: string) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || (/^\d*\.?\d+$/.test(value) && Number(value) >= 0), message)

const schema = z.object({
  supplier: z.string().trim().max(200, 'Supplier name is too long'),
  purchase_date: z.string().trim().min(1, 'When did you buy it?'),
  inbound_shipping_cost: nonNegative('Enter a non-negative amount, or leave it blank'),
  tax_amount: nonNegative('Enter a non-negative amount, or leave it blank'),
  tax_recoverable: z.boolean(),
  order_reference: z.string().trim().max(100, 'Order reference is too long'),
  notes: z.string().trim(),
})

type FormValues = z.infer<typeof schema>

/** Per-spool allocation, derived on read — nothing here is stored. */
export function SpoolAllocationTable({
  spools,
  currencySymbol = '$',
}: {
  spools: SpoolLandedCost[]
  currencySymbol?: string
}) {
  if (spools.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="no-spools-yet">
        No spools are attached to this purchase yet. Attach them and each one&apos;s share of
        the shipping appears here.
      </p>
    )
  }

  return (
    <div className="space-y-3" data-testid="spool-allocation">
      {spools.map((spool) => (
        <div
          key={spool.spool_id}
          className="rounded-md border p-3"
          data-testid={`spool-allocation-${spool.spool_id}`}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium">{spool.spool_label ?? spool.spool_id}</span>
            <span className="tabular-nums">
              {spool.cost_per_gram === null ? (
                <span className="text-muted-foreground">per-gram cost not yet known</span>
              ) : (
                <>
                  {formatMoney(spool.cost_per_gram, currencySymbol)} per usable gram
                </>
              )}
            </span>
          </div>

          <dl className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Price paid</dt>
              <dd className="tabular-nums">{formatMoney(spool.purchase_price, currencySymbol)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Share of shipping</dt>
              <dd className="tabular-nums">
                {formatMoney(spool.allocated_shipping, currencySymbol)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">
                {spool.tax_recoverable ? 'Tax (recoverable, excluded)' : 'Share of tax'}
              </dt>
              <dd className="tabular-nums">{formatMoney(spool.allocated_tax, currencySymbol)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Landed cost</dt>
              <dd className="tabular-nums font-medium">
                {formatMoney(spool.total_landed_cost, currencySymbol)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted-foreground">Usable weight</dt>
              <dd className="tabular-nums">
                {spool.usable_weight_grams} g
                {spool.unusable_remainder_grams !== '0' && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    ({spool.unusable_remainder_grams} g unusable)
                  </span>
                )}
              </dd>
            </div>
          </dl>

          {spool.even_split_fallback && (
            <p
              className="mt-2 text-xs text-muted-foreground"
              data-testid={`even-split-${spool.spool_id}`}
            >
              Shipping was split evenly rather than by weight — one of these spools has no
              recorded weight.
            </p>
          )}

          {spool.incomplete_reasons.length > 0 && (
            <ul
              className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground"
              data-testid={`incomplete-${spool.spool_id}`}
            >
              {spool.incomplete_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}

          {spool.derivation.length > 0 && (
            <details className="mt-2 text-xs text-muted-foreground">
              <summary className="cursor-pointer">How this was worked out</summary>
              <ol className="mt-1 list-decimal space-y-0.5 pl-5">
                {spool.derivation.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </details>
          )}
        </div>
      ))}
    </div>
  )
}

interface FilamentPurchaseFormProps {
  /** Omitted to record a new purchase; given to correct an existing one. */
  purchaseId?: string
  currencySymbol?: string
  onSaved?: (purchase: FilamentPurchase) => void
}

export function FilamentPurchaseForm({
  purchaseId,
  currencySymbol = '$',
  onSaved,
}: FilamentPurchaseFormProps) {
  // A viewer reads a purchase but cannot record one (T238, FR-007c).
  const { user } = useAuth()
  const canEdit = canEditOperationalFigures(user)

  const { purchase, isLoading, error } = useFilamentPurchase(purchaseId)
  const {
    createPurchaseAsync,
    updatePurchaseAsync,
    isSaving,
    error: saveError,
  } = useSaveFilamentPurchase()

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      supplier: '',
      purchase_date: '',
      inbound_shipping_cost: '',
      tax_amount: '',
      tax_recoverable: false,
      order_reference: '',
      notes: '',
    },
  })

  useEffect(() => {
    if (purchase && !form.formState.isDirty) {
      form.reset({
        supplier: purchase.supplier ?? '',
        purchase_date: purchase.purchase_date,
        inbound_shipping_cost: purchase.inbound_shipping_cost,
        tax_amount: purchase.tax_amount,
        tax_recoverable: purchase.tax_recoverable,
        order_reference: purchase.order_reference ?? '',
        notes: purchase.notes ?? '',
      })
    }
  }, [purchase, form])

  const onSubmit = async (values: FormValues) => {
    const payload = {
      supplier: values.supplier || null,
      purchase_date: values.purchase_date,
      inbound_shipping_cost: values.inbound_shipping_cost || '0',
      tax_amount: values.tax_amount || '0',
      tax_recoverable: values.tax_recoverable,
      order_reference: values.order_reference || null,
      notes: values.notes || null,
    }

    let saved
    try {
      saved = purchaseId
        ? await updatePurchaseAsync({ purchaseId, data: payload })
        : await createPurchaseAsync(payload)
    } catch {
      // The mutation's own `error` state drives the message the operator sees,
      // so there is nothing to report here. What this catch is for is stopping
      // the rejection propagating out of react-hook-form's submit handler,
      // where it becomes an unhandled rejection: the UI has handled the
      // failure, and an unhandled rejection would still reach the window
      // handler and Sentry as though it had not. The form is deliberately
      // *not* reset, so the operator's input survives for another attempt.
      return
    }

    form.reset({ ...values })
    onSaved?.(saved)
  }

  if (purchaseId && isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
        </CardContent>
      </Card>
    )
  }

  if (purchaseId && error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>Failed to load this purchase</AlertDescription>
      </Alert>
    )
  }

  return (
    <Card data-testid="filament-purchase-form">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Package className="h-5 w-5" />
          <CardTitle>{purchaseId ? 'Filament purchase' : 'Record a filament purchase'}</CardTitle>
        </div>
        <CardDescription>
          Record what the order cost and Batchivo works out what each spool landed at —
          shipping spread by weight, because weight is what drove the postage.
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

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <fieldset disabled={!canEdit} className="m-0 min-w-0 space-y-4 border-0 p-0">
            <FormField
              control={form.control}
              name="supplier"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Supplier</FormLabel>
                  <FormControl>
                    <Input placeholder="Polymaker" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="purchase_date"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Purchase date</FormLabel>
                  <FormControl>
                    <Input type="date" {...field} />
                  </FormControl>
                  <FormDescription>
                    The date these landed costs are dated from.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="inbound_shipping_cost"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Inbound shipping</FormLabel>
                  <FormControl>
                    <Input inputMode="decimal" placeholder="18.00" {...field} />
                  </FormControl>
                  <FormDescription>
                    What it cost to get the order to you. Spread across the spools by weight.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="tax_amount"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Sales tax</FormLabel>
                  <FormControl>
                    <Input inputMode="decimal" placeholder="6.50" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="tax_recoverable"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start gap-3 rounded-md border p-3">
                  <FormControl>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      aria-label="This tax is recoverable"
                    />
                  </FormControl>
                  <div className="space-y-1">
                    <FormLabel className="font-normal">This tax is recoverable</FormLabel>
                    <FormDescription>
                      Recoverable tax is money you get back, so it is left out of what the
                      filament cost you. Non-recoverable tax is part of the cost.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="order_reference"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Order reference</FormLabel>
                  <FormControl>
                    <Input placeholder="PO-4471" {...field} />
                  </FormControl>
                  <FormDescription>
                    For reconciling against the supplier&apos;s invoice later.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Notes</FormLabel>
                  <FormControl>
                    <Textarea className="min-h-[80px]" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            </fieldset>
            {!canEdit && (
              <p className="text-sm text-muted-foreground" data-testid="read-only-notice">
                Recording a purchase needs a member, admin or owner role.
              </p>
            )}
            <div className="flex items-center gap-4 pt-2">
              <Button type="submit" disabled={isSaving || !form.formState.isDirty || !canEdit}>
                {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {purchaseId ? 'Save purchase' : 'Record purchase'}
              </Button>
            </div>
          </form>
        </Form>

        {purchase && (
          <>
            <Separator />
            <div className="space-y-2">
              <h3 className="font-medium">What each spool landed at</h3>
              {purchase.allocation_notes.length > 0 && (
                <Alert data-testid="allocation-notes">
                  <Info className="h-4 w-4" />
                  <AlertDescription>
                    <ul className="list-disc space-y-0.5 pl-5">
                      {purchase.allocation_notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
              <SpoolAllocationTable
                spools={purchase.spools}
                currencySymbol={currencySymbol}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
