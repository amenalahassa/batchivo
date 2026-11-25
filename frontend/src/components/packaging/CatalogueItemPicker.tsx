/**
 * A checklist of the standard packaging catalogue (spec 006), shared by the
 * "Add standard packaging" dialog and onboarding step 5.
 *
 * An item the shop already has is shown ticked and disabled; one seeded once
 * and since deleted is marked "previously removed" so the operator can leave
 * it out.
 */

import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { formatMoney } from '@/lib/money'
import type { CatalogueItem } from '@/types/packagingCatalogue'

import { PACKAGING_KIND_LABELS, itemSize } from './catalogueHelpers'

interface CatalogueItemPickerProps {
  items: CatalogueItem[]
  selected: Set<string>
  onToggle: (key: string, checked: boolean) => void
  currencySymbol: string
}

export function CatalogueItemPicker({
  items,
  selected,
  onToggle,
  currencySymbol,
}: CatalogueItemPickerProps) {
  return (
    <ul className="divide-y rounded-md border" data-testid="catalogue-items">
      {items.map((item) => {
        const id = `catalogue-${item.key}`
        return (
          <li key={item.key} className="flex items-center gap-3 px-3 py-2">
            <Checkbox
              id={id}
              checked={item.present || selected.has(item.key)}
              disabled={item.present}
              onCheckedChange={(checked) => onToggle(item.key, checked === true)}
              aria-label={item.name}
            />
            <label htmlFor={id} className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="font-medium">{item.name}</span>
              <span className="text-muted-foreground">{PACKAGING_KIND_LABELS[item.kind]}</span>
              <span className="text-muted-foreground">{itemSize(item)}</span>
              <span className="text-muted-foreground">
                {item.typical_cost ? `~${formatMoney(item.typical_cost, currencySymbol)}` : 'no typical cost'}
              </span>
              {item.present && <Badge variant="secondary">Already added</Badge>}
              {item.previously_removed && !item.present && (
                <Badge variant="outline">Previously removed</Badge>
              )}
            </label>
          </li>
        )
      })}
    </ul>
  )
}
