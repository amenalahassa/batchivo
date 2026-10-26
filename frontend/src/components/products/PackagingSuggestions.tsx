/**
 * PackagingSuggestions -- which stocked box or mailer an item fits in (FR-014 to FR-020).
 *
 * The list is asked for, never kept (FR-022): pressing "Suggest packaging"
 * fetches it, best first, each with the orientation it fits in, the room left
 * on each axis and the empty volume. Accepting one makes it the product's (or
 * the size variant's) packaging (FR-023).
 *
 * No cost appears here (FR-021). The packaging cost is the line the existing
 * cost breakdown shows for the accepted box; a second figure beside it would
 * be a second pricing implementation.
 */

import { useState } from 'react'
import { AlertTriangle, Check, Loader2, PackageSearch, ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useAcceptPackaging, usePackagingSuggestions } from '@/hooks/usePackaging'
import type { InnerSize, PackagingSuggestion } from '@/types/packaging'

interface PackagingSuggestionsProps {
  productId: string
  /** Suggest for this size variant, from its effective dimensions. */
  variantId?: string | null
  /** False for a viewer: suggestions are shown, Accept is not (FR-023). */
  canEdit: boolean
  /** Where to send the operator when the item has no dimensions yet. */
  dimensionsAnchor?: string
}

function size(d: InnerSize): string {
  return `${d.length_mm} × ${d.width_mm} × ${d.height_mm} mm`
}

function orientationText(s: PackagingSuggestion): string {
  const [l, w, h] = s.orientation
  if (l === 'length' && w === 'width' && h === 'height') return 'As it stands'
  return `Item ${l} along the box length, ${w} across, ${h} up`
}

export function PackagingSuggestions({
  productId,
  variantId,
  canEdit,
  dimensionsAnchor,
}: PackagingSuggestionsProps) {
  const [asked, setAsked] = useState(false)
  const query = usePackagingSuggestions(productId, variantId, asked)
  const accept = useAcceptPackaging(productId)

  const advice = query.data
  const warnings = advice?.warnings ?? []
  const incomplete = warnings
    .filter((w) => w.startsWith('incomplete_container:'))
    .map((w) => w.slice('incomplete_container:'.length))

  return (
    <div className="space-y-3" data-testid="packaging-suggestions">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => (asked ? query.refetch() : setAsked(true))}
          disabled={query.isFetching}
        >
          {query.isFetching ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <PackageSearch className="mr-2 h-4 w-4" />
          )}
          Suggest packaging
        </Button>
        {advice && (
          <span className="text-xs text-muted-foreground">
            {advice.clearance_mm} mm clearance on every side
          </span>
        )}
        {advice?.fragile && (
          <Badge variant="outline" className="bg-amber-500/10 text-amber-700 border-amber-200">
            <ShieldAlert className="mr-1 h-3 w-3" />
            Fragile
          </Badge>
        )}
      </div>

      {query.isError && (
        <p className="text-sm text-destructive">
          Could not get suggestions: {(query.error as Error).message}
        </p>
      )}

      {warnings.includes('dimensions_required') && (
        <p className="text-sm text-muted-foreground">
          Record this item's dimensions first
          {dimensionsAnchor ? (
            <>
              {' '}
              (<a className="underline" href={`#${dimensionsAnchor}`}>dimensions</a>)
            </>
          ) : null}
          ; nothing can be suggested without them.
        </p>
      )}

      {warnings.includes('nothing_fits') && advice?.minimum_inner && (
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Nothing you stock fits. A box would need at least {size(advice.minimum_inner)} inside.
          </span>
        </div>
      )}

      {incomplete.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Not considered, inner size incomplete: {incomplete.join(', ')}
        </p>
      )}

      {advice && advice.suggestions.length > 0 && (
        <ul className="divide-y rounded-md border">
          {advice.suggestions.map((s, index) => (
            <li key={s.consumable_id} className="flex items-start justify-between gap-3 p-3">
              <div className="space-y-1 text-sm">
                <div className="flex flex-wrap items-center gap-2 font-medium">
                  <span>
                    {index + 1}. {s.name}
                  </span>
                  <span className="font-normal text-muted-foreground">{size(s.inner)}</span>
                  {s.in_stock ? (
                    <Badge variant="outline" className="bg-green-500/10 text-green-700 border-green-200">
                      In stock
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="bg-gray-500/10 text-gray-600">
                      Out of stock
                    </Badge>
                  )}
                  {s.is_current && <Badge>Current</Badge>}
                </div>
                <div className="text-xs text-muted-foreground">
                  {orientationText(s)} · room {s.room_mm.length} / {s.room_mm.width} /{' '}
                  {s.room_mm.height} mm · empty {s.empty_volume_ml} ml
                </div>
                <div className="text-xs text-muted-foreground">
                  {s.void_fill
                    ? `Void fill: ${s.void_fill.quantity} × ${s.void_fill.name}`
                    : 'No void fill stocked'}
                  {s.wrap && ` · Wrap in ${s.wrap.name}`}
                </div>
              </div>
              {canEdit && !s.is_current && (
                <Button
                  size="sm"
                  onClick={() =>
                    accept.mutate({
                      consumable_id: s.consumable_id,
                      quantity: 1,
                      variant_id: variantId ?? null,
                    })
                  }
                  disabled={accept.isPending}
                >
                  {accept.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="mr-2 h-4 w-4" />
                  )}
                  Accept
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {accept.isError && (
        <p className="text-sm text-destructive">
          Could not accept: {(accept.error as Error).message}
        </p>
      )}
    </div>
  )
}
