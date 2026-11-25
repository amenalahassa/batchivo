/**
 * ProductPricingEditor Component
 *
 * Editor for managing per-channel product pricing.
 * Shows prices, fees, and profit calculations by sales channel.
 *
 * ## Periods and tiers (task T100, FR-039)
 *
 * A price is no longer one row per channel. It is a row per channel, quantity
 * tier and effective period, so this screen has to make three things visible
 * that it previously could not:
 *
 * - **Which prices are in effect now.** Only current rows are listed. A
 *   superseded price is history and belongs behind the History button, not in
 *   the table of what the product sells for.
 * - **The quantity tier each price applies from.** Tiers are half-open lower
 *   bounds, so "10+" means ten or more and the price at exactly ten is the
 *   "10+" one. Shown as a column rather than left to the operator to infer.
 * - **That changing a price opens a new period rather than overwriting one.**
 *   The dialog says so, and the history dialog shows the periods that result.
 *
 * The history dialog deliberately shows **no profit or margin figures**.
 * Valuing a past price against today's cost is precisely the restatement
 * FR-038 exists to prevent; a settled order's own snapshot is where a
 * historical margin lives.
 */

import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import {
  Calculator,
  Loader2,
  Plus,
  Trash2,
  TrendingUp,
  TrendingDown,
  Edit,
  History,
  Receipt,
} from 'lucide-react'

import {
  addProductPricing,
  updateProductPricing,
  removeProductPricing,
  getProductPricingHistory,
  type ProductPricing,
} from '@/lib/api/products'
import { useCurrency } from '@/hooks/useCurrency'
import {
  averageMoney,
  compareMoney,
  formatMoney,
  formatPercent,
  symbolForCurrency,
} from '@/lib/money'
import { listSalesChannels } from '@/lib/api/sales-channels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Switch } from '@/components/ui/switch'
import { MarginBasisLabel } from '@/components/pricing/MarginBasisLabel'
import { PriceFinderDialog } from '@/components/pricing/PriceFinderDialog'
import { ProductMarginBreakdown } from '@/components/pricing/ProductMarginBreakdown'
import { useAuth } from '@/contexts/AuthContext'
import { canEditMonetaryPolicy } from '@/lib/pricing/permissions'

const pricingFormSchema = z.object({
  sales_channel_id: z.string().uuid('Must select a sales channel'),
  list_price: z.string().regex(/^\d+(\.\d{1,2})?$/, 'Must be a valid price (e.g., 19.99)'),
  is_active: z.boolean().default(true),
  // Kept as a string through the form so an empty field stays empty rather
  // than becoming NaN, and coerced once on submit.
  min_quantity: z
    .string()
    .regex(/^\d+$/, 'Must be a whole number of units')
    .refine((value) => Number(value) >= 1, 'A tier starts at one unit or more')
    .default('1'),
  // Empty means today, which is what the API does with an absent date.
  valid_from: z.string().default(''),
})

type PricingFormValues = z.infer<typeof pricingFormSchema>

/** A tier's lower bound as an operator reads it: "1+", "10+". */
function tierLabel(minQuantity: number): string {
  return `${minQuantity}+`
}

/**
 * A period as a sentence, with the open end named rather than left blank.
 *
 * "Since 12 Oct 2026" reads as current; an empty end column would read as
 * missing data.
 */
function periodLabel(from: string, to: string | null): string {
  const fmt = (value: string) =>
    new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  return to === null ? `Since ${fmt(from)}` : `${fmt(from)} - ${fmt(to)}`
}

interface ProductPricingEditorProps {
  productId: string
  pricing: ProductPricing[]
  /**
   * The make-cost as the exact decimal string the API sent, not a float.
   * This screen shows the same figure as the product list and the product
   * detail page, and a float conversion on the way here is what used to let
   * them disagree in the last cent.
   */
  makeCost: string
}

export function ProductPricingEditor({ productId, pricing, makeCost }: ProductPricingEditorProps) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingPricing, setEditingPricing] = useState<ProductPricing | null>(null)
  //: The channel whose price history is open, or null for closed.
  const [historyChannelId, setHistoryChannelId] = useState<string | null>(null)
  // The channel whose full margin is open: fees, postage, reserves (T244).
  // Which row's breakdown is open: its channel and its tier's quantity, so a
  // tier row's margin is the margin at that tier (T258).
  const [marginTarget, setMarginTarget] = useState<{
    channelId: string
    quantity: number
  } | null>(null)
  //: The row whose price finder is open, or null for closed.
  const [finderPricing, setFinderPricing] = useState<ProductPricing | null>(null)
  const queryClient = useQueryClient()
  const { currency } = useCurrency()
  const { user } = useAuth()
  // A price is a monetary decision (FR-002, FR-007a). A viewer reads the
  // margin at every rung and takes none of them.
  const canSetPrice = canEditMonetaryPolicy(user)

  // Fetch available sales channels
  const { data: salesChannelsData } = useQuery({
    queryKey: ['sales-channels', { limit: 100 }],
    queryFn: () => listSalesChannels({ limit: 100 }),
  })

  const form = useForm<z.input<typeof pricingFormSchema>, unknown, PricingFormValues>({
    resolver: zodResolver(pricingFormSchema),
    defaultValues: {
      sales_channel_id: '',
      list_price: '',
      is_active: true,
      min_quantity: '1',
      valid_from: '',
    },
  })

  const addMutation = useMutation({
    mutationFn: (data: PricingFormValues) =>
      addProductPricing(productId, {
        sales_channel_id: data.sales_channel_id,
        list_price: data.list_price,
        is_active: data.is_active,
        min_quantity: Number(data.min_quantity),
        // Omitted rather than sent empty: the API reads an absent date as
        // today, and sending "" would be a validation error.
        ...(data.valid_from ? { valid_from: data.valid_from } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product', productId] })
      queryClient.invalidateQueries({ queryKey: ['product-pricing-history', productId] })
      form.reset()
      setDialogOpen(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ pricingId, data }: { pricingId: string; data: Partial<PricingFormValues> }) =>
      updateProductPricing(productId, pricingId, {
        list_price: data.list_price,
        is_active: data.is_active,
        ...(data.valid_from ? { valid_from: data.valid_from } : {}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product', productId] })
      queryClient.invalidateQueries({ queryKey: ['product-pricing-history', productId] })
      setEditingPricing(null)
    },
  })

  const removeMutation = useMutation({
    mutationFn: (pricingId: string) => removeProductPricing(productId, pricingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product', productId] })
      queryClient.invalidateQueries({ queryKey: ['product-pricing-history', productId] })
    },
  })

  // The history for whichever channel's dialog is open. Fetched on demand
  // rather than with the product: a price history grows without bound and
  // most visits to this screen never open it.
  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['product-pricing-history', productId, historyChannelId],
    queryFn: () => getProductPricingHistory(productId, historyChannelId as string),
    enabled: historyChannelId !== null,
  })

  const onSubmit = (values: PricingFormValues) => {
    if (editingPricing) {
      updateMutation.mutate({
        pricingId: editingPricing.id,
        data: values,
      })
    } else {
      addMutation.mutate(values)
    }
  }

  const handleEdit = (pricingItem: ProductPricing) => {
    setEditingPricing(pricingItem)
    form.reset({
      sales_channel_id: pricingItem.sales_channel_id,
      list_price: pricingItem.list_price,
      is_active: pricingItem.is_active,
      min_quantity: String(pricingItem.min_quantity),
      // Left empty rather than prefilled with the current period's start: an
      // edit opens a *new* period, and prefilling the old start date would
      // invite the operator to reuse it, which overlaps and is refused.
      valid_from: '',
    })
    setDialogOpen(true)
  }

  const handleDialogClose = () => {
    setDialogOpen(false)
    setEditingPricing(null)
    form.reset()
  }

  const handleAddClick = () => {
    setEditingPricing(null)
    form.reset({
      sales_channel_id: '',
      list_price: '',
      is_active: true,
      min_quantity: '1',
      valid_from: '',
    })
    setDialogOpen(true)
  }

  const handleToggleActive = (pricingItem: ProductPricing) => {
    updateMutation.mutate({
      pricingId: pricingItem.id,
      data: { is_active: !pricingItem.is_active },
    })
  }

  const handleFindPrice = (pricingItem: ProductPricing) => {
    setFinderPricing(pricingItem)
  }

  /**
   * A price the operator took from the solver or the ladder.
   *
   * It arrives as a *draft*, not a saved row: the edit dialog opens with the
   * figure in it and the operator still presses save. US4 scenario 5 makes the
   * solved price a proposal they apply or reject, and silently writing it
   * would be the one behaviour that requirement rules out.
   */
  const handleApplyFoundPrice = (pricingItem: ProductPricing, price: string) => {
    setFinderPricing(null)
    setEditingPricing(pricingItem)
    form.reset({
      sales_channel_id: pricingItem.sales_channel_id,
      list_price: price,
      is_active: pricingItem.is_active,
      min_quantity: String(pricingItem.min_quantity),
      valid_from: '',
    })
    setDialogOpen(true)
  }

  // Only current rows belong on this screen. `pricing` is the product's
  // current pricing from the API, but a caller passing a full history should
  // not end up with a superseded price listed as what the product sells for.
  const currentPricing = pricing.filter((p) => p.valid_to === null)

  // Every channel stays selectable, because a channel may now carry several
  // prices -- one per quantity tier. Only the *tier* is unique, and the API
  // refuses a duplicate with a 409 naming the tier that already exists.
  const selectableChannels = salesChannelsData?.channels ?? []
  // A list price is in the currency of the channel it is listed on (T276).
  const formChannelId = form.watch('sales_channel_id')
  const formChannelSymbol = symbolForCurrency(
    selectableChannels.find((channel) => channel.id === formChannelId)?.currency_code,
    currency.symbol,
  )

  // Grouped by channel, tiers ascending, so a channel's 1+/10+/50+ rows read
  // as one ladder rather than being scattered by insertion order.
  const sortedPricing = [...currentPricing].sort(
    (a, b) =>
      (a.channel_name ?? '').localeCompare(b.channel_name ?? '') ||
      a.min_quantity - b.min_quantity
  )

  // Averages are over the base tier only. Counting a channel's 1+, 10+ and
  // 50+ prices as three channels would drag the average toward whichever
  // channel happens to have the most tiers.
  //
  // Each figure averaged here is the engine's -- `profit` and
  // `margin_percentage` come off the API per channel, and nothing on this
  // screen re-derives either (Constitution III). What is computed is the mean
  // of what it was sent, and it is computed in string space: these used to be
  // summed with `parseFloat`, which is the conversion Constitution IV rules
  // out for a monetary figure. `averageMoney` is the one place a rounding
  // happens, and it says so.
  //
  // And within one currency only (T261): a channel selling in dollars and one
  // in pounds have no average profit. Each currency's channels are averaged
  // apart and shown in that currency.
  const activePricing = currentPricing.filter((p) => p.is_active && p.min_quantity === 1)
  const rowSymbol = (row: { currency?: string }) => symbolForCurrency(row.currency, currency.symbol)
  const averagesByCurrency = Object.entries(
    activePricing.reduce<Record<string, typeof activePricing>>((groups, row) => {
      const key = rowSymbol(row)
      groups[key] = [...(groups[key] ?? []), row]
      return groups
    }, {}),
  ).map(([symbol, rows]) => ({
    symbol,
    profit: averageMoney(rows.map((p) => p.profit)),
    margin: averageMoney(
      rows.map((p) => p.margin_percentage),
      1,
    ),
  }))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground space-x-4">
          <span>
            Make Cost: <span className="font-semibold">{formatMoney(makeCost, currency.symbol)}</span>
          </span>
          {averagesByCurrency.map((group) => (
            <span key={group.symbol} data-testid={`pricing-averages-${group.symbol.trim()}`}>
              <span>•</span>{' '}
              <span>
                Avg Profit{averagesByCurrency.length > 1 ? ` (${group.symbol.trim()})` : ''}:{' '}
                <span className="font-semibold">{formatMoney(group.profit, group.symbol)}</span>
              </span>{' '}
              <span>•</span>{' '}
              <span>
                Avg Margin{averagesByCurrency.length > 1 ? ` (${group.symbol.trim()})` : ''}:{' '}
                <span className="font-semibold">{formatPercent(group.margin)}</span>
              </span>
            </span>
          ))}
        </div>
        <Dialog open={dialogOpen} onOpenChange={(open) => !open && handleDialogClose()}>
          <DialogTrigger asChild>
            <Button size="sm" onClick={handleAddClick}>
              <Plus className="mr-2 h-4 w-4" />
              Add Pricing
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>
                {editingPricing ? 'Edit Pricing' : 'Add Channel Pricing'}
              </DialogTitle>
              <DialogDescription>
                {editingPricing
                  ? 'Changing the price opens a new period. The old price stays on record, so orders already placed keep reporting what they were charged.'
                  : 'Set a price for a sales channel, optionally from a quantity break.'}
              </DialogDescription>
            </DialogHeader>

            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                <FormField
                  control={form.control}
                  name="sales_channel_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Sales Channel</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value}
                        disabled={!!editingPricing}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Choose a channel..." />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {editingPricing ? (
                            <SelectItem value={editingPricing.sales_channel_id}>
                              {editingPricing.channel_name}
                            </SelectItem>
                          ) : selectableChannels.length === 0 ? (
                            <SelectItem value="none" disabled>
                              No channels configured
                            </SelectItem>
                          ) : (
                            selectableChannels.map((channel) => (
                              <SelectItem key={channel.id} value={channel.id}>
                                {channel.name} ({channel.platform_type})
                              </SelectItem>
                            ))
                          )}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="list_price"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>List Price ({formChannelSymbol})</FormLabel>
                      <FormControl>
                        <Input type="number" step="0.01" min="0" placeholder="19.99" {...field} />
                      </FormControl>
                      <FormDescription>
                        The selling price on this channel
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="min_quantity"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Applies from quantity</FormLabel>
                      <FormControl>
                        {/* `readOnly`, not `disabled`. react-hook-form reads a
                            disabled input's value as undefined, which fails
                            this field's validation and silently blocks the
                            whole form from submitting -- so editing a price
                            would do nothing at all. */}
                        <Input
                          type="number"
                          step="1"
                          min="1"
                          placeholder="1"
                          readOnly={!!editingPricing}
                          aria-disabled={!!editingPricing}
                          className={editingPricing ? 'bg-muted text-muted-foreground' : undefined}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        {/* Half-open lower bound. Said plainly, because "10+"
                            is ambiguous about whether ten itself is included
                            and the answer changes the price of a ten-unit
                            order. */}
                        {editingPricing ? (
                          <>
                            A price for this quantity <strong>or more</strong>. A tier cannot be
                            moved -- add another price instead.
                          </>
                        ) : (
                          <>
                            A price for this quantity <strong>or more</strong>. Leave at 1 for the
                            normal price; set 10 for a price that applies from ten units up.
                          </>
                        )}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="valid_from"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Applies from date</FormLabel>
                      <FormControl>
                        <Input type="date" {...field} />
                      </FormControl>
                      <FormDescription>
                        {editingPricing
                          ? 'Leave blank for today. The current price keeps applying up to the day before, so orders already placed still report what they were charged.'
                          : 'Leave blank for today. Backdate it only if this price really applied earlier.'}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="is_active"
                  render={({ field }) => (
                    <FormItem className="flex flex-row items-center justify-between rounded-lg border p-3">
                      <div className="space-y-0.5">
                        <FormLabel>Active</FormLabel>
                        <FormDescription>
                          Whether this pricing is currently active
                        </FormDescription>
                      </div>
                      <FormControl>
                        <Switch checked={field.value} onCheckedChange={field.onChange} />
                      </FormControl>
                    </FormItem>
                  )}
                />

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleDialogClose}
                    disabled={addMutation.isPending || updateMutation.isPending}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={
                      addMutation.isPending ||
                      updateMutation.isPending ||
                      (!editingPricing && selectableChannels.length === 0)
                    }
                  >
                    {(addMutation.isPending || updateMutation.isPending) && (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    )}
                    {editingPricing ? 'Update' : 'Add Pricing'}
                  </Button>
                </DialogFooter>
              </form>
            </Form>
          </DialogContent>
        </Dialog>
      </div>

      {currentPricing.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          No pricing set yet. Click "Add Pricing" to set prices for sales channels.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Channel</TableHead>
              <TableHead className="w-[70px] text-right">Qty</TableHead>
              <TableHead className="w-[100px] text-right">List Price</TableHead>
              <TableHead className="w-[100px] text-right">Fees</TableHead>
              <TableHead className="w-[100px] text-right">Net Revenue</TableHead>
              <TableHead className="w-[100px] text-right">Profit</TableHead>
              <TableHead className="w-[80px] text-right">Margin</TableHead>
              <TableHead className="w-[60px] text-center">Active</TableHead>
              <TableHead className="w-[120px]">Effective</TableHead>
              <TableHead className="w-[110px]"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedPricing.map((pricingItem) => {
              // The engine's own profit and margin, kept as the decimal
              // strings it sent. They were parsed to floats to be formatted
              // and compared; both are done on the strings now, so the row
              // shows exactly what the engine computed (Constitution IV).
              const profit = pricingItem.profit ?? null
              const margin = pricingItem.margin_percentage ?? null
              const isProfitable = compareMoney(profit, '0') > 0

              return (
                <TableRow key={pricingItem.id} className={!pricingItem.is_active ? 'opacity-50' : ''}>
                  <TableCell>
                    <div className="space-y-0.5">
                      <div className="font-medium">{pricingItem.channel_name || 'Unknown Channel'}</div>
                      <div className="text-xs text-muted-foreground">
                        {pricingItem.platform_type}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {/* The tier's lower bound. "1+" is shown rather than left
                        blank: a blank would read as "no tier", and every price
                        has one. */}
                    {tierLabel(pricingItem.min_quantity)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-medium">
                    {formatMoney(pricingItem.list_price, rowSymbol(pricingItem))}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    -{formatMoney(pricingItem.platform_fee, rowSymbol(pricingItem))}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(pricingItem.net_revenue, rowSymbol(pricingItem))}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className={`flex items-center justify-end gap-1 tabular-nums font-semibold ${
                      isProfitable ? 'text-green-600' : 'text-red-600'
                    }`}>
                      {isProfitable ? (
                        <TrendingUp className="h-3 w-3" />
                      ) : (
                        <TrendingDown className="h-3 w-3" />
                      )}
                      {formatMoney(profit, rowSymbol(pricingItem))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    {/* FR-031b: the basis travels with the percentage. These
                        rows compute profit over the price the customer paid,
                        so the basis is `customer_total` -- named rather than
                        assumed, because the same sale reads differently on
                        the other two bases. */}
                    <div className="flex flex-col items-end gap-1">
                      <Badge
                        variant="outline"
                        className={
                          compareMoney(margin, '30') >= 0
                            ? 'bg-green-500/10 text-green-600 border-green-200'
                            : compareMoney(margin, '15') >= 0
                              ? 'bg-yellow-500/10 text-yellow-600 border-yellow-200'
                              : 'bg-red-500/10 text-red-600 border-red-200'
                        }
                      >
                        {formatPercent(margin)}
                      </Badge>
                      <MarginBasisLabel
                        basis="customer_total"
                        short
                        className="text-[10px] font-normal"
                      />
                      {/* FR-043: profit per machine-hour beside the margin. */}
                      <span
                        className="text-[10px] text-muted-foreground tabular-nums whitespace-nowrap"
                        data-testid={`profit-per-machine-hour-${pricingItem.id}`}
                      >
                        {pricingItem.profit_per_machine_hour == null
                          ? 'untimed'
                          : `${formatMoney(pricingItem.profit_per_machine_hour, rowSymbol(pricingItem))}/machine-hr`}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center">
                    <Switch
                      checked={pricingItem.is_active}
                      onCheckedChange={() => handleToggleActive(pricingItem)}
                      disabled={updateMutation.isPending}
                    />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    {periodLabel(pricingItem.valid_from, pricingItem.valid_to)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Margin breakdown for ${pricingItem.channel_name || 'this channel'}`}
                        onClick={() =>
                          setMarginTarget({
                            channelId: pricingItem.sales_channel_id,
                            quantity: pricingItem.min_quantity,
                          })
                        }
                      >
                        <Receipt className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Price history for ${pricingItem.channel_name || 'this channel'}`}
                        onClick={() => setHistoryChannelId(pricingItem.sales_channel_id)}
                      >
                        <History className="h-4 w-4" />
                      </Button>
                      {/* US4: state a target margin and read the price, or
                          read the margin across a range and choose (FR-007). */}
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Find a price for ${pricingItem.channel_name || 'this channel'}`}
                        onClick={() => handleFindPrice(pricingItem)}
                      >
                        <Calculator className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Edit price for ${pricingItem.channel_name || 'this channel'}`}
                        onClick={() => handleEdit(pricingItem)}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            aria-label={`Stop selling at ${tierLabel(pricingItem.min_quantity)} on ${pricingItem.channel_name || 'this channel'}`}
                            disabled={removeMutation.isPending}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Stop selling at this price</AlertDialogTitle>
                            <AlertDialogDescription>
                              {/* Says what actually happens. Calling this
                                  "remove" when it closes a period would make
                                  an operator think past orders had lost their
                                  price. */}
                              This closes the current period for "{pricingItem.channel_name}" at{' '}
                              {tierLabel(pricingItem.min_quantity)}, so the product stops selling at
                              this price. The price stays in the history, and orders already placed
                              keep reporting what they were charged.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => removeMutation.mutate(pricingItem.id)}>
                              Close period
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      {/* Price history for one channel.
          Reads as a list of periods and carries no profit or margin column,
          on purpose: a past price valued against today's cost is the
          restatement FR-038 exists to prevent, and showing one here would be
          the most natural place for that mistake to reappear. */}
      {/* T244: the margin with everything behind it -- each fee with its basis,
          clamp and incidence, postage against shipping charged, reserves, and
          how much of the make-cost is evidence (FR-018, FR-024, FR-029). */}
      <Dialog
        open={marginTarget !== null}
        onOpenChange={(open) => !open && setMarginTarget(null)}
      >
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Margin breakdown</DialogTitle>
            <DialogDescription>
              What {marginTarget && marginTarget.quantity > 1
                ? `an order of ${marginTarget.quantity}`
                : 'one unit'}{' '}
              earns on{' '}
              {pricing.find((row) => row.sales_channel_id === marginTarget?.channelId)
                ?.channel_name ?? 'this channel'}{' '}
              at the price in effect today.
            </DialogDescription>
          </DialogHeader>
          {marginTarget && (
            <ProductMarginBreakdown
              productId={productId}
              channelId={marginTarget.channelId}
              quantity={marginTarget.quantity}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={historyChannelId !== null}
        onOpenChange={(open) => !open && setHistoryChannelId(null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Price history</DialogTitle>
            <DialogDescription>
              Every price this product has carried on{' '}
              {currentPricing.find((p) => p.sales_channel_id === historyChannelId)
                ?.channel_name ?? 'this channel'}
              , newest first.
            </DialogDescription>
          </DialogHeader>

          {historyLoading ? (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading history...
            </div>
          ) : !history || history.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground">
              No price history for this channel yet.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Effective</TableHead>
                  <TableHead className="w-[70px] text-right">Qty</TableHead>
                  <TableHead className="w-[110px] text-right">List Price</TableHead>
                  <TableHead className="w-[90px] text-center">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.map((row) => (
                  <TableRow key={row.id} className={row.is_current ? '' : 'text-muted-foreground'}>
                    <TableCell className="whitespace-nowrap">
                      {periodLabel(row.valid_from, row.valid_to)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {tierLabel(row.min_quantity)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-medium">
                      {formatMoney(row.list_price, rowSymbol(row))}
                    </TableCell>
                    <TableCell className="text-center">
                      <Badge variant={row.is_current ? 'default' : 'outline'}>
                        {row.is_current ? 'Current' : 'Superseded'}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          <p className="text-xs text-muted-foreground">
            No margin is shown against a past price. Valuing it against today&apos;s cost would
            restate history; a settled order reports the margin frozen onto it at the time of
            sale.
          </p>
        </DialogContent>
      </Dialog>

      <PriceFinderDialog
        open={finderPricing !== null}
        onOpenChange={(open) => !open && setFinderPricing(null)}
        productId={productId}
        channelId={finderPricing?.sales_channel_id ?? null}
        channelName={finderPricing?.channel_name ?? undefined}
        currentPrice={finderPricing?.list_price ?? null}
        onApply={
          canSetPrice && finderPricing
            ? (price) => handleApplyFoundPrice(finderPricing, price)
            : undefined
        }
        currencySymbol={finderPricing ? rowSymbol(finderPricing) : currency.symbol}
      />
    </div>
  )
}
