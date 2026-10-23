/**
 * PriceFinderDialog — the two ways to arrive at a price, in one place.
 *
 * US4 inverts the old loop. Instead of typing a price and reading a margin,
 * the operator states a target margin and receives the price that achieves it,
 * solved against the very price the percentage fees are charged on (FR-032).
 * `PriceSolverPanel` does that.
 *
 * But some prices are not a calculation. "What will a customer pay" is a
 * market judgement, and FR-007 is explicit that the system must never store or
 * compute one: it shows margin across a ladder of prices and the operator
 * chooses. `PriceLadder` does that.
 *
 * They belong together because they answer the same question from two ends,
 * and an operator who has only the solver will treat its output as the answer
 * rather than as one input to their own judgement.
 *
 * ## Nothing here publishes
 *
 * A solved price is a proposal (FR-032's assumption, US4 scenario 5). `onApply`
 * hands it back to the pricing editor, where it becomes a draft the operator
 * saves — writing to a connected channel is a separate, operator-initiated
 * action and is out of scope for this feature.
 */

import { useState } from 'react'
import { Calculator, ListOrdered } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PriceLadder } from './PriceLadder'
import { PriceSolverPanel } from './PriceSolverPanel'
import { usePriceLadder, useSolvePrice } from '@/hooks/usePricing'
import { compareMoney, divideMoney, multiplyMoney, subtractMoney } from '@/lib/money'
import type { Money } from '@/types/pricing'

export interface PriceFinderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  productId: string
  /** Null while no channel is chosen; the dialog then renders no content. */
  channelId: string | null
  channelName?: string
  /** The price in effect, marked on the ladder as a fact, not a suggestion. */
  currentPrice?: Money | null
  /**
   * Take a price. Omitted, both panels are read-only — the right state for a
   * viewer, since setting a price is a write (FR-007a).
   */
  onApply?: (price: string) => void
  currencySymbol?: string
}

/**
 * The ladder's default span, derived from the price already in effect rather
 * than from a constant: a fixed range would put its midpoint near a figure
 * nobody chose, and a midpoint on a price screen reads as a recommendation.
 */
function defaultRange(currentPrice: Money | null | undefined) {
  if (!currentPrice || compareMoney(currentPrice, '0') <= 0) return null

  // In decimal, not through a double. These bounds are prices: they go to the
  // ladder endpoint and come back as the points an operator picks a price
  // from, so they are money from here to there (Constitution IV, task T165).
  //
  // The multiplications are exact and the rounding to the penny happens once,
  // on each bound, at the edge where the figure becomes a price.
  const toThePenny = (amount: Money | null) => (amount === null ? null : divideMoney(amount, 1))

  const from = toThePenny(multiplyMoney(currentPrice, '0.7'))
  const to = toThePenny(multiplyMoney(currentPrice, '1.3'))
  const step = toThePenny(divideMoney(subtractMoney(to, from), 10))

  const atLeastAPenny = (amount: Money | null) =>
    amount === null || compareMoney(amount, '0.01') < 0 ? '0.01' : amount

  return {
    price_from: atLeastAPenny(from),
    price_to: atLeastAPenny(to),
    step: atLeastAPenny(step),
  }
}

export function PriceFinderDialog({
  open,
  onOpenChange,
  productId,
  channelId,
  channelName,
  currentPrice,
  onApply,
  currencySymbol = '$',
}: PriceFinderDialogProps) {
  const { solve, result, isSolving, error, reset } = useSolvePrice(
    productId,
    channelId ?? undefined
  )

  // The bounds and the step are inputs, never constants (T086a).
  const [range, setRange] = useState(() => defaultRange(currentPrice))
  const { ladder, isLoading: ladderLoading, error: ladderError } = usePriceLadder(
    productId,
    channelId ?? undefined,
    // The ladder stays unfetched until there is a range to fetch it for.
    open && channelId && range ? range : undefined
  )

  const apply = (price: string) => {
    onApply?.(price)
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Find a price{channelName ? ` — ${channelName}` : ''}
          </DialogTitle>
          <DialogDescription>
            Name the margin you want and read the price, or read the margin across a range of
            prices and choose. Nothing here is published to a channel.
          </DialogDescription>
        </DialogHeader>

        {channelId ? (
          <Tabs defaultValue="solve" className="space-y-4">
            <TabsList>
              <TabsTrigger value="solve" className="gap-2">
                <Calculator className="h-4 w-4" />
                From a target margin
              </TabsTrigger>
              <TabsTrigger value="ladder" className="gap-2">
                <ListOrdered className="h-4 w-4" />
                Across a range
              </TabsTrigger>
            </TabsList>

            <TabsContent value="solve">
              <PriceSolverPanel
                result={result}
                isSolving={isSolving}
                error={error}
                onSolve={solve}
                onApply={onApply ? apply : undefined}
                onDismiss={reset}
                currencySymbol={currencySymbol}
              />
            </TabsContent>

            <TabsContent value="ladder" className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="ladder-from">From</Label>
                  <Input
                    id="ladder-from"
                    inputMode="decimal"
                    value={range?.price_from ?? ''}
                    onChange={(event) =>
                      setRange((previous) => ({
                        price_from: event.target.value,
                        price_to: previous?.price_to ?? '',
                        step: previous?.step ?? '1.00',
                      }))
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ladder-to">To</Label>
                  <Input
                    id="ladder-to"
                    inputMode="decimal"
                    value={range?.price_to ?? ''}
                    onChange={(event) =>
                      setRange((previous) => ({
                        price_from: previous?.price_from ?? '',
                        price_to: event.target.value,
                        step: previous?.step ?? '1.00',
                      }))
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="ladder-step">Step</Label>
                  <Input
                    id="ladder-step"
                    inputMode="decimal"
                    value={range?.step ?? ''}
                    onChange={(event) =>
                      setRange((previous) => ({
                        price_from: previous?.price_from ?? '',
                        price_to: previous?.price_to ?? '',
                        step: event.target.value,
                      }))
                    }
                  />
                </div>
              </div>

              <PriceLadder
                ladder={ladder}
                isLoading={ladderLoading}
                error={ladderError}
                currentPrice={currentPrice}
                onChoose={onApply ? apply : undefined}
                currencySymbol={currencySymbol}
              />
            </TabsContent>
          </Tabs>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
