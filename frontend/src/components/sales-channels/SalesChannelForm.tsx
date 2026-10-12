/**
 * SalesChannelForm Component
 *
 * Form for creating and editing sales channels.
 */

import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'

import {
  createSalesChannel,
  updateSalesChannel,
  getPlatformDisplayName,
  type SalesChannel,
  type SalesChannelCreateRequest,
  type SalesChannelUpdateRequest,
  type PlatformType,
} from '@/lib/api/sales-channels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

const PLATFORM_TYPES: PlatformType[] = [
  'fair',
  'online_shop',
  'shopify',
  'ebay',
  'etsy',
  'amazon',
  'other',
]

const salesChannelFormSchema = z.object({
  name: z.string().min(1, 'Name is required').max(200, 'Name must be 200 characters or less'),
  platform_type: z.enum(['fair', 'online_shop', 'shopify', 'ebay', 'etsy', 'amazon', 'other']),
  fee_percentage: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, 'Must be a valid percentage')
    .optional()
    .default('0'),
  fee_fixed: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, 'Must be a valid amount')
    .optional()
    .default('0'),
  monthly_cost: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, 'Must be a valid amount')
    .optional()
    .default('0'),
  is_active: z.boolean().optional().default(true),

  // Channel economics (Tier 2). Each of these is an operator decision in the
  // sense of FR-002 -- a reserve they choose to hold, a threshold they set --
  // so none of them is ever written by an automated process.
  tax_remitter: z.enum(['marketplace', 'operator']).optional().default('operator'),
  expected_discount_pct: z
    .string()
    .regex(/^\d+(\.\d{1,4})?$/, 'Must be a valid percentage')
    .optional()
    .default('0'),
  expected_refund_pct: z
    .string()
    .regex(/^\d+(\.\d{1,4})?$/, 'Must be a valid percentage')
    .optional()
    .default('0'),
  free_shipping_threshold: z
    .string()
    .regex(/^\d*(\.\d{1,2})?$/, 'Must be a valid amount')
    .optional()
    .default(''),
  rounding_rule: z.string().max(20).optional().default(''),
  currency_code: z
    .string()
    .regex(/^[A-Za-z]{3}$/, 'Use a three-letter currency code')
    .optional()
    .default('GBP'),
  offsite_ads_opt_in: z.boolean().optional().default(false),
})

type SalesChannelFormValues = z.infer<typeof salesChannelFormSchema>

interface SalesChannelFormProps {
  channel?: SalesChannel
  mode: 'create' | 'edit'
}

export function SalesChannelForm({ channel, mode }: SalesChannelFormProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const form = useForm<z.input<typeof salesChannelFormSchema>, unknown, SalesChannelFormValues>({
    resolver: zodResolver(salesChannelFormSchema),
    defaultValues: {
      name: channel?.name || '',
      platform_type: channel?.platform_type || 'other',
      fee_percentage: channel?.fee_percentage || '0',
      fee_fixed: channel?.fee_fixed || '0',
      monthly_cost: channel?.monthly_cost || '0',
      is_active: channel?.is_active ?? true,
      tax_remitter: channel?.tax_remitter ?? 'operator',
      expected_discount_pct: channel?.expected_discount_pct || '0',
      expected_refund_pct: channel?.expected_refund_pct || '0',
      free_shipping_threshold: channel?.free_shipping_threshold ?? '',
      rounding_rule: channel?.rounding_rule ?? '',
      currency_code: channel?.currency_code || 'GBP',
      offsite_ads_opt_in: channel?.offsite_ads_opt_in ?? false,
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: SalesChannelCreateRequest) => createSalesChannel(data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['sales-channels'] })
      navigate({ to: '/sales-channels/$channelId', params: { channelId: data.id } })
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data: SalesChannelUpdateRequest) => updateSalesChannel(channel!.id, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['sales-channels'] })
      queryClient.invalidateQueries({ queryKey: ['sales-channel', channel!.id] })
      navigate({ to: '/sales-channels/$channelId', params: { channelId: data.id } })
    },
  })

  const onSubmit = (values: SalesChannelFormValues) => {
    const data = {
      name: values.name,
      platform_type: values.platform_type,
      fee_percentage: values.fee_percentage || '0',
      fee_fixed: values.fee_fixed || '0',
      monthly_cost: values.monthly_cost || '0',
      is_active: values.is_active,
      tax_remitter: values.tax_remitter,
      expected_discount_pct: values.expected_discount_pct || '0',
      expected_refund_pct: values.expected_refund_pct || '0',
      // An empty threshold is "no free shipping offered", which is null rather
      // than zero: a threshold of zero would mean everything ships free.
      free_shipping_threshold: values.free_shipping_threshold
        ? values.free_shipping_threshold
        : null,
      rounding_rule: values.rounding_rule ? values.rounding_rule : null,
      currency_code: (values.currency_code || 'GBP').toUpperCase(),
      offsite_ads_opt_in: values.offsite_ads_opt_in,
    }

    if (mode === 'create') {
      createMutation.mutate(data)
    } else {
      updateMutation.mutate(data)
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  // Live fee preview
  const watchFeePercentage = form.watch('fee_percentage')
  const watchFeeFixed = form.watch('fee_fixed')
  const exampleSale = 20
  const feePercentage = parseFloat(watchFeePercentage || '0')
  const feeFixed = parseFloat(watchFeeFixed || '0')
  const totalFee = (exampleSale * feePercentage / 100) + feeFixed
  const netAmount = exampleSale - totalFee

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        {/* Basic Information */}
        <Card>
          <CardHeader>
            <CardTitle>Channel Information</CardTitle>
            <CardDescription>Basic details about this sales channel</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g., Local Craft Fair" {...field} />
                    </FormControl>
                    <FormDescription>Display name for this channel</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="platform_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Platform Type</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select platform type" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {PLATFORM_TYPES.map((type) => (
                          <SelectItem key={type} value={type}>
                            {getPlatformDisplayName(type)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <FormDescription>Type of sales platform</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </CardContent>
        </Card>

        {/* Fee Structure */}
        <Card>
          <CardHeader>
            <CardTitle>Fee Structure (legacy)</CardTitle>
            <CardDescription>
              One percentage plus one fixed amount, kept while the migration settles.
              A real marketplace charges several fees on different amounts — set those
              up under Fee rules, which is what the margin is now computed from. These
              two no longer feed it.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <FormField
                control={form.control}
                name="fee_percentage"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Fee Percentage (%)</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" max="100" placeholder="0" {...field} />
                    </FormControl>
                    <FormDescription>Percentage of each sale</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="fee_fixed"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Fixed Fee (£)</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" placeholder="0.00" {...field} />
                    </FormControl>
                    <FormDescription>Fixed amount per sale</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="monthly_cost"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Monthly Cost (£)</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" placeholder="0.00" {...field} />
                    </FormControl>
                    <FormDescription>Subscription/booth fee</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Fee Preview */}
            <div className="rounded-lg border bg-muted/50 p-4">
              <div className="text-sm font-medium mb-2">Fee Preview (£{exampleSale} sale)</div>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-xs text-muted-foreground">Total Fee</div>
                  <div className="font-semibold">£{totalFee.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Net Amount</div>
                  <div className="font-semibold text-green-600">£{netAmount.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Effective Rate</div>
                  <div className="font-semibold">{((totalFee / exampleSale) * 100).toFixed(1)}%</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Channel economics (Tier 2) */}
        <Card>
          <CardHeader>
            <CardTitle>Channel Economics</CardTitle>
            <CardDescription>
              The levers that decide what a sale on this channel is actually worth.
              Every one of these is your decision and nothing automated will change
              it.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                control={form.control}
                name="tax_remitter"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Who remits sales tax</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="marketplace">The marketplace</SelectItem>
                        <SelectItem value="operator">You do</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      This does not change any margin — tax is never counted as revenue
                      either way. It decides whether the tax collected is tracked as
                      money you owe.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="currency_code"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Currency</FormLabel>
                    <FormControl>
                      <Input placeholder="GBP" maxLength={3} {...field} />
                    </FormControl>
                    <FormDescription>
                      Three-letter code this channel displays prices in
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="expected_discount_pct"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Expected discount (%)</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" max="100" placeholder="0" {...field} />
                    </FormControl>
                    <FormDescription>
                      Sales you expect to discount, averaged. Reduces planned revenue
                      rather than cost.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="expected_refund_pct"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Refund reserve (%)</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" max="100" placeholder="0" {...field} />
                    </FormControl>
                    <FormDescription>
                      Share of revenue held back against refunds. Held, not spent — it
                      is not a cost.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="free_shipping_threshold"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Free shipping above</FormLabel>
                    <FormControl>
                      <Input type="number" step="0.01" min="0" placeholder="Leave blank for none" {...field} />
                    </FormControl>
                    <FormDescription>
                      Blank means you never ship free. Where you do, remember the
                      postage is still yours to pay — it shows as its own margin line.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="rounding_rule"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Price rounding</FormLabel>
                    <Select
                      onValueChange={(value) =>
                        field.onChange(value === 'none' ? '' : value)
                      }
                      value={field.value || 'none'}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="none">No rounding</SelectItem>
                        <SelectItem value="psychological_99">End in .99</SelectItem>
                        <SelectItem value="psychological_95">End in .95</SelectItem>
                        <SelectItem value="whole">Whole units</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Applied to a solved price, shown to you as an adjustment before
                      anything is saved
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="offsite_ads_opt_in"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4">
                  <div className="space-y-0.5 pr-4">
                    <FormLabel className="text-base">Offsite advertising</FormLabel>
                    <FormDescription>
                      Whether you have opted into the marketplace advertising its
                      listings for a share of the sale. Add the charge as a fee rule
                      with a share of orders, so it is labelled an expectation rather
                      than a certainty.
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        {/* Status - only show in edit mode */}
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
                        Inactive channels are hidden from pricing options
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
            onClick={() =>
              navigate({
                to: channel ? `/sales-channels/${channel.id}` : '/sales-channels',
              })
            }
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {mode === 'create' ? 'Create Channel' : 'Save Changes'}
          </Button>
        </div>
      </form>
    </Form>
  )
}
