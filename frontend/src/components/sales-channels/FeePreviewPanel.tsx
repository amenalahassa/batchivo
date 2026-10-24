/**
 * FeePreviewPanel — what this channel would charge on an order (T246).
 *
 * `POST /sales-channels/{id}/fee-rules/preview` lets anyone with a member's
 * role ask the fee engine about a hypothetical order without creating
 * anything, and `useFeePreview` had no screen. It sits beside the rule editor
 * so an operator can check a rule they just wrote: the itemised stack with
 * each basis, the clamps that bound, the fees charged at an expected
 * incidence, and any date no rule covers (FR-021c, T236).
 *
 * The amounts typed here are sent as the strings typed (Constitution IV), and
 * every figure shown is the engine's.
 */

import { useState, type FormEvent } from 'react'
import { AlertCircle, Calculator, Loader2 } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FeeBreakdownTable } from '@/components/pricing/FeeBreakdownTable'
import { useFeePreview } from '@/hooks/useFeeRules'

const AMOUNT = /^\d+(\.\d{1,2})?$/

interface FeePreviewPanelProps {
  channelId: string
  currencySymbol?: string
}

export function FeePreviewPanel({ channelId, currencySymbol }: FeePreviewPanelProps) {
  const preview = useFeePreview(channelId)
  const [itemSubtotal, setItemSubtotal] = useState('')
  const [shipping, setShipping] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [invalid, setInvalid] = useState<string | null>(null)

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!AMOUNT.test(itemSubtotal.trim())) {
      setInvalid('Enter the item price, e.g. 64.99')
      return
    }
    if (shipping.trim() !== '' && !AMOUNT.test(shipping.trim())) {
      setInvalid('Enter shipping as an amount, or leave it blank')
      return
    }
    if (!/^[1-9]\d*$/.test(quantity.trim())) {
      setInvalid('Enter a whole quantity of at least 1')
      return
    }
    setInvalid(null)
    preview.mutate({
      item_subtotal: itemSubtotal.trim(),
      shipping_revenue: shipping.trim() || undefined,
      quantity: Number.parseInt(quantity.trim(), 10),
    })
  }

  const result = preview.data

  return (
    <Card data-testid="fee-preview-panel">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Calculator className="h-5 w-5" />
          <CardTitle>Try the fees</CardTitle>
        </div>
        <CardDescription>
          What this channel would charge on an order, from the rules in force today. Nothing is
          saved.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-4 sm:items-end">
          <div className="space-y-1">
            <Label htmlFor="fee-preview-item">Item price</Label>
            <Input
              id="fee-preview-item"
              inputMode="decimal"
              placeholder="64.99"
              value={itemSubtotal}
              onChange={(event) => setItemSubtotal(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="fee-preview-shipping">Shipping charged</Label>
            <Input
              id="fee-preview-shipping"
              inputMode="decimal"
              placeholder="0.00"
              value={shipping}
              onChange={(event) => setShipping(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="fee-preview-quantity">Quantity</Label>
            <Input
              id="fee-preview-quantity"
              inputMode="numeric"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={preview.isPending}>
            {preview.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Preview fees
          </Button>
        </form>

        {invalid && (
          <p className="text-sm text-destructive" role="alert">
            {invalid}
          </p>
        )}

        {preview.error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>No preview</AlertTitle>
            <AlertDescription>{preview.error.message}</AlertDescription>
          </Alert>
        )}

        {result && (
          <div className="space-y-3" data-testid="fee-preview-result">
            {(result.incomplete_reasons ?? []).length > 0 && (
              <Alert data-testid="fee-preview-incomplete">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Some fees could not be priced</AlertTitle>
                <AlertDescription>
                  <ul className="list-disc pl-4">
                    {(result.incomplete_reasons ?? []).map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            <FeeBreakdownTable
              charges={result.charges}
              periodic={result.periodic}
              total={result.total}
              currencySymbol={currencySymbol}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
