/**
 * "Add standard packaging" (spec 006, US2): pick catalogue items to add to the
 * shop's packaging, each with typical sizes and cost marked as defaults.
 *
 * Every item not yet present starts selected, including one the operator
 * removed before: adding the catalogue restores it, marked "previously
 * removed" so the operator can clear it (spec edge case).
 */

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useCurrency } from '@/hooks/useCurrency'
import {
  useApplyPackagingCatalogue,
  usePackagingCatalogue,
} from '@/hooks/usePackagingCatalogue'
import { apiErrorDetail } from '@/lib/apiError'

import { CatalogueItemPicker } from './CatalogueItemPicker'
import { selectableKeys } from './catalogueHelpers'

interface AddCatalogueDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AddCatalogueDialog({ open, onOpenChange }: AddCatalogueDialogProps) {
  const { currency } = useCurrency()
  const { catalogue, isLoading } = usePackagingCatalogue(open)
  const apply = useApplyPackagingCatalogue()
  const [selected, setSelected] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (open && catalogue) {
      setSelected(new Set(selectableKeys(catalogue.items)))
    }
  }, [open, catalogue])

  const toggle = (key: string, checked: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (checked) next.add(key)
      else next.delete(key)
      return next
    })

  const submit = () => {
    if (selected.size === 0) return
    apply.mutate([...selected], { onSuccess: () => onOpenChange(false) })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add standard packaging</DialogTitle>
          <DialogDescription>
            Common boxes, mailers, void fill and wrap with typical sizes and costs. Each figure is
            marked as a default until you measure or price it.
            {catalogue ? ` Catalogue version ${catalogue.version}, ${catalogue.as_of}.` : ''}
          </DialogDescription>
        </DialogHeader>

        {isLoading || !catalogue ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin" aria-label="Loading catalogue" />
          </div>
        ) : (
          <CatalogueItemPicker
            items={catalogue.items}
            selected={selected}
            onToggle={toggle}
            currencySymbol={currency.symbol}
          />
        )}

        {apply.isError && (
          <p className="text-sm text-destructive">
            Could not add the packaging: {apiErrorDetail(apply.error)}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={apply.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={apply.isPending || selected.size === 0}>
            {apply.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Add {selected.size} item{selected.size === 1 ? '' : 's'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
