/**
 * OrderParcelDialog — confirm the parcels an order is sent in (T065, research D10).
 *
 * Opened from "Mark as Shipped". It starts from the advisor's suggestion
 * (GET /orders/{id}/packaging-suggestions): one row per parcel with its box
 * and void fill, each editable, and the postage marked as an estimate.
 * Confirming records the parcels once, takes their packaging from stock and
 * sets the postage they determine; the dialog then shows what was stored and
 * any stock that went below zero, and hands on to shipping.
 *
 * Quantities are counts; every size, weight and amount is the decimal string
 * the API sent, shown as is.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Package, Plus, Trash2 } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useConfirmOrderParcels, useOrderPackagingSuggestions } from '@/hooks/usePackaging'
import { consumablesApi } from '@/lib/api/consumables'
import { draftFrom, toConfirmInput, type DraftParcel } from '@/lib/packaging'
import type { ConfirmParcelsResult, ConfirmedParcel } from '@/types/packaging'

function sizeOf(parcel: ConfirmedParcel): string | null {
  const { outer_length_mm: l, outer_width_mm: w, outer_height_mm: h } = parcel
  return l && w && h ? `${l} × ${w} × ${h} mm` : null
}

/** The parcels an order was sent in, read-only. */
export function ConfirmedParcels({ parcels }: { parcels: ConfirmedParcel[] }) {
  return (
    <ul className="space-y-2" data-testid="confirmed-parcels">
      {parcels.map((parcel) => (
        <li key={parcel.id} className="rounded-md border p-2 text-sm">
          <div className="font-medium">Parcel {parcel.sequence}</div>
          <div className="text-muted-foreground">
            {parcel.items.map((i) => `${i.quantity} × ${i.name ?? i.consumable_id}`).join(', ')}
          </div>
          <div className="text-xs text-muted-foreground">
            {[sizeOf(parcel), parcel.packed_weight_grams && `${parcel.packed_weight_grams} g`]
              .filter(Boolean)
              .join(' · ')}
          </div>
        </li>
      ))}
    </ul>
  )
}

interface OrderParcelDialogProps {
  orderId: string
  orderNumber: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called once the parcels are confirmed, or skipped, to go on to shipping. */
  onContinue: () => void
}

export function OrderParcelDialog({
  orderId,
  orderNumber,
  open,
  onOpenChange,
  onContinue,
}: OrderParcelDialogProps) {
  const suggestions = useOrderPackagingSuggestions(orderId, open)
  const confirm = useConfirmOrderParcels(orderId)
  const packaging = useQuery({
    queryKey: ['consumables', 'packaging'],
    queryFn: () => consumablesApi.list({ packaging_kind: 'box,mailer,void_fill', page_size: 100 }),
    enabled: open,
  })
  const [draft, setDraft] = useState<DraftParcel[]>([])
  const [result, setResult] = useState<ConfirmParcelsResult | null>(null)

  useEffect(() => {
    if (open) {
      setDraft(draftFrom(suggestions.data))
      setResult(null)
    }
  }, [open, suggestions.data])

  const options = packaging.data?.consumables ?? []
  const containers = options.filter((c) => c.packaging_kind === 'box' || c.packaging_kind === 'mailer')
  const fillers = options.filter((c) => c.packaging_kind === 'void_fill')
  const estimate = suggestions.data?.estimated_postage

  const update = (index: number, change: Partial<DraftParcel>) =>
    setDraft((rows) => rows.map((row, i) => (i === index ? { ...row, ...change } : row)))

  const addParcel = () =>
    setDraft((rows) => [
      ...rows,
      { containerId: containers[0]?.id ?? '', fillId: null, fillQuantity: 0, contents: [] },
    ])

  const submit = async () => {
    setResult(await confirm.mutateAsync(toConfirmInput(draft)))
  }

  const complete = draft.length > 0 && draft.every((p) => p.containerId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Parcels for {orderNumber}
          </DialogTitle>
          <DialogDescription>
            Confirm what this order goes out in. The packaging is taken from stock and the
            postage is set from these parcels.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-3">
            <ConfirmedParcels parcels={result.parcels} />
            <p className="text-sm">
              Postage:{' '}
              {result.postage.amount ?? <span className="text-muted-foreground">unknown</span>}
              {result.postage.reason && (
                <span className="block text-xs text-muted-foreground">{result.postage.reason}</span>
              )}
            </p>
            {result.warnings.map((w) => (
              <Alert key={w.consumable_id} variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>
                  Stock of{' '}
                  {options.find((c) => c.id === w.consumable_id)?.name ?? w.consumable_id} is now{' '}
                  {w.on_hand}.
                </AlertDescription>
              </Alert>
            ))}
          </div>
        ) : suggestions.isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-label="Loading suggestions" />
        ) : (
          <div className="space-y-3">
            {suggestions.data?.warnings.map((w, i) => (
              <Alert key={i}>
                <AlertDescription>
                  {w.code === 'dimensions_required'
                    ? `${w.sku} has no dimensions, so no parcel can be suggested. Choose one below.`
                    : 'No box you stock holds these items. Choose one below.'}
                </AlertDescription>
              </Alert>
            ))}
            {draft.map((parcel, index) => (
              <div key={index} className="grid gap-2 rounded-md border p-3" data-testid="draft-parcel">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">Parcel {index + 1}</span>
                  {draft.length > 1 && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove parcel ${index + 1}`}
                      onClick={() => setDraft((rows) => rows.filter((_, i) => i !== index))}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
                {parcel.contents.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {parcel.contents.map((c) => `${c.quantity} × ${c.sku}`).join(', ')}
                  </p>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label>Box or mailer</Label>
                    <Select
                      value={parcel.containerId}
                      onValueChange={(value) => update(index, { containerId: value })}
                    >
                      <SelectTrigger aria-label={`Container for parcel ${index + 1}`}>
                        <SelectValue placeholder="Choose" />
                      </SelectTrigger>
                      <SelectContent>
                        {containers.map((c) => (
                          <SelectItem key={c.id} value={c.id}>
                            {c.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {fillers.length > 0 && (
                    <div className="space-y-1">
                      <Label htmlFor={`fill-${index}`}>Void fill (units)</Label>
                      <Input
                        id={`fill-${index}`}
                        type="number"
                        min={0}
                        value={parcel.fillQuantity}
                        onChange={(e) =>
                          update(index, {
                            fillQuantity: Math.max(0, parseInt(e.target.value) || 0),
                            fillId: parcel.fillId ?? fillers[0].id,
                          })
                        }
                      />
                    </div>
                  )}
                </div>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={addParcel} disabled={!containers.length}>
              <Plus className="mr-1 h-4 w-4" />
              Add parcel
            </Button>
            {estimate && (
              <p className="text-sm" data-testid="estimated-postage">
                Postage {estimate.amount ?? 'unknown'}{' '}
                <Badge variant="outline">estimate</Badge>
                {estimate.reason && (
                  <span className="block text-xs text-muted-foreground">{estimate.reason}</span>
                )}
              </p>
            )}
            {confirm.isError && (
              <Alert variant="destructive">
                <AlertDescription>
                  Not confirmed:{' '}
                  {confirm.error instanceof Error ? confirm.error.message : 'unknown error'}
                </AlertDescription>
              </Alert>
            )}
          </div>
        )}

        <DialogFooter>
          {result ? (
            <Button onClick={onContinue}>Continue to shipping</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onContinue}>
                Skip
              </Button>
              <Button onClick={submit} disabled={!complete || confirm.isPending}>
                {confirm.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Confirm parcels
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
