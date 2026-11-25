/**
 * FilamentPurchaseDialog — where a purchase gets recorded.
 *
 * FR-008a asks for the *purchase* to be recordable, not just the spool,
 * because a landed per-gram cost cannot otherwise be derived: one shipping
 * charge covers several spools and has to be allocated across them by weight
 * (FR-008b). `FilamentPurchaseForm` does that work and shows the allocation it
 * arrived at (FR-008f); it had no way in.
 *
 * The dialog lists what has already been recorded, because a purchase is the
 * kind of record an operator corrects — a spool weight was wrong, the invoice
 * arrived with a different shipping figure — and FR-008's edge case says the
 * allocation is then recomputed for every spool in it.
 */

import { useState } from 'react'
import { Loader2, Plus, Receipt } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { FilamentPurchaseForm } from './FilamentPurchaseForm'
import { useFilamentPurchases } from '@/hooks/usePricing'

interface FilamentPurchaseDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  currencySymbol?: string
}

export function FilamentPurchaseDialog({
  open,
  onOpenChange,
  currencySymbol = '$',
}: FilamentPurchaseDialogProps) {
  // Undefined records a new purchase; an id corrects that one.
  const [editingId, setEditingId] = useState<string | undefined>(undefined)
  const { purchases, isLoading } = useFilamentPurchases({ limit: 20 })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setEditingId(undefined)
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Filament purchases</DialogTitle>
          <DialogDescription>
            One shipping charge usually covers several spools. Record the purchase and the
            cost of each spool is worked out from it, shipping split by weight.
          </DialogDescription>
        </DialogHeader>

        {purchases.length > 0 || isLoading ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-muted-foreground">Recorded</h3>
              {editingId ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditingId(undefined)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Record another
                </Button>
              ) : null}
            </div>

            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading purchases…
              </div>
            ) : (
              <ScrollArea className="max-h-40">
                <ul className="space-y-1">
                  {purchases.map((purchase) => (
                    <li key={purchase.id}>
                      <button
                        type="button"
                        onClick={() => setEditingId(purchase.id)}
                        aria-current={editingId === purchase.id ? 'true' : undefined}
                        className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted ${
                          editingId === purchase.id ? 'bg-muted' : ''
                        }`}
                      >
                        <Receipt className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-medium">
                          {purchase.supplier || 'Unnamed supplier'}
                        </span>
                        <span className="text-muted-foreground">{purchase.purchase_date}</span>
                        <span className="ml-auto tabular-nums text-muted-foreground">
                          {currencySymbol}
                          {purchase.inbound_shipping_cost} shipping
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </ScrollArea>
            )}

            <Separator />
          </div>
        ) : null}

        <FilamentPurchaseForm
          // Remounting on a change of target clears the previous purchase's
          // values; without it the form keeps a dirty field from the last one.
          key={editingId ?? 'new'}
          purchaseId={editingId}
          currencySymbol={currencySymbol}
          onSaved={(purchase) => setEditingId(purchase.id)}
        />
      </DialogContent>
    </Dialog>
  )
}
