/**
 * ProductMarginBreakdown — everything behind one channel's margin (T244).
 *
 * `GET /products/{id}/pricing/{channel}/margin` returns the itemised fees with
 * their bases, clamps and expected-incidence flags, postage paid against the
 * shipping charged, the reserves, the margin's basis and the observed share of
 * the make-cost -- and no screen read it, so the price list showed one
 * `platform_fee` and a percentage nobody could explain (US3/AC1, FR-018).
 *
 * Every figure is the engine's decimal string, rendered as sent
 * (Constitution IV); nothing here recomputes a total (Constitution III).
 */

import { AlertCircle, Loader2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table'
import { FeeBreakdownTable } from '@/components/pricing/FeeBreakdownTable'
import { MarginFigure } from '@/components/pricing/MarginBasisLabel'
import { useProductMargin } from '@/hooks/useFeeRules'
import { useCurrency } from '@/hooks/useCurrency'
import { compareMoney, formatMoney, formatPercent, formatShare } from '@/lib/money'
import { cn } from '@/lib/utils'

interface ProductMarginBreakdownProps {
  productId: string
  channelId: string
  /** The channel's display symbol; the margin is served in its currency. */
  currencySymbol?: string
  /**
   * Units on the line, so a quantity tier's row shows the margin at its tier
   * -- the whole line's revenue, cost, fees and one parcel (T258).
   */
  quantity?: number
}

export function ProductMarginBreakdown({
  productId,
  channelId,
  currencySymbol,
  quantity = 1,
}: ProductMarginBreakdownProps) {
  const { currency } = useCurrency()
  const symbol = currencySymbol ?? currency.symbol
  const { margin, isLoading, error } = useProductMargin(
    productId,
    channelId,
    quantity > 1 ? { quantity } : undefined,
  )

  if (isLoading) {
    return (
      <div className="flex justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }

  if (error || !margin) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>No margin to show</AlertTitle>
        <AlertDescription>
          {error?.message ?? 'This product is not priced on this channel.'}
        </AlertDescription>
      </Alert>
    )
  }

  const shippingLoses = compareMoney(margin.shipping_net, '0') < 0

  return (
    <div className="space-y-4" data-testid="product-margin-breakdown">
      <MarginFigure
        marginPct={margin.margin_pct}
        basis={margin.margin_basis}
        label={margin.margin_basis_label}
        emphasis
      />

      {margin.incomplete_reasons.length > 0 && (
        <Alert data-testid="margin-incomplete">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>This margin is not complete</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {margin.incomplete_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <Table>
        <TableBody>
          <TableRow>
            <TableCell>List price</TableCell>
            <TableCell className="text-right tabular-nums">
              {formatMoney(margin.list_price, symbol)}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell>Shipping charged</TableCell>
            <TableCell className="text-right tabular-nums">
              {formatMoney(margin.shipping_revenue, symbol)}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell>Postage paid</TableCell>
            <TableCell className="text-right tabular-nums">
              -{formatMoney(margin.postage_paid, symbol)}
            </TableCell>
          </TableRow>
          <TableRow data-testid="margin-shipping-net">
            <TableCell className="font-medium">Shipping margin</TableCell>
            <TableCell
              className={cn(
                'text-right tabular-nums font-medium',
                shippingLoses && 'text-red-600',
              )}
            >
              {formatMoney(margin.shipping_net, symbol)}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell>Make cost</TableCell>
            <TableCell className="text-right tabular-nums">
              -{formatMoney(margin.make_cost, symbol)}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <div>
        <h4 className="mb-2 text-sm font-medium">Fees</h4>
        <FeeBreakdownTable
          charges={margin.fees}
          total={margin.fee_total}
          currencySymbol={symbol}
        />
      </div>

      {margin.deductions.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-medium">Reserves</h4>
          <Table>
            <TableBody>
              {margin.deductions.map((deduction) => (
                <TableRow key={deduction.key} data-testid={`margin-deduction-${deduction.key}`}>
                  <TableCell>
                    {deduction.label}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {formatPercent(deduction.rate_pct, { places: 2 })} of{' '}
                      {formatMoney(deduction.basis_amount, symbol)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    -{formatMoney(deduction.amount, symbol)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Table>
        <TableBody>
          <TableRow>
            <TableCell className="font-medium">Net revenue</TableCell>
            <TableCell className="text-right tabular-nums">
              {formatMoney(margin.net_revenue, symbol)}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell className="font-semibold">Profit</TableCell>
            <TableCell
              className={cn(
                'text-right tabular-nums font-semibold',
                compareMoney(margin.profit, '0') > 0 ? 'text-green-600' : 'text-red-600',
              )}
              data-testid="margin-profit"
            >
              {formatMoney(margin.profit, symbol)}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <p className="text-xs text-muted-foreground" data-testid="margin-observed-share">
        {formatShare(margin.observed_share)} of the make-cost rests on observed or measured
        figures; {formatShare(margin.assumed_share)} is still assumed.
      </p>
    </div>
  )
}
