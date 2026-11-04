/**
 * The Packaging page's list (spec 006, US1): boxes, mailers, void fill and
 * wrap, each with the figures its kind needs (FR-003).
 *
 * Packaging is one table with the consumables (research D1); this view asks
 * for the packaging kinds only. A figure that came from the catalogue's
 * defaults (provenance `assumed`) carries a "default" badge, a box the
 * advisor cannot use yet says why, and each container says which postage
 * services take it and which products ship in it.
 *
 * Operational figures: a viewer reads the list without the add, edit or
 * delete controls.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Edit, Library, Plus, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { AddConsumableDialog } from '@/components/inventory/AddConsumableDialog'
import { DeleteConsumableDialog } from '@/components/inventory/DeleteConsumableDialog'
import { EditConsumableDialog } from '@/components/inventory/EditConsumableDialog'
import { useAuth } from '@/contexts/AuthContext'
import { useCurrency } from '@/hooks/useCurrency'
import { useCarriers } from '@/hooks/usePostageCatalogue'
import { consumablesApi } from '@/lib/api/consumables'
import { formatMoney } from '@/lib/money'
import { canEditOperationalFigures } from '@/lib/pricing/permissions'
import type { ConsumableTypeResponse } from '@/types/consumable'
import type { PackagingKind } from '@/types/packaging'

import { AddCatalogueDialog } from './AddCatalogueDialog'
import { PACKAGING_KIND_LABELS, PACKAGING_KINDS, packagingListParams } from './catalogueHelpers'
import { CatalogueNotice } from './CatalogueNotice'
import { serviceLabel } from './serviceLabels'

/**
 * An assumed figure: "default" when it came with a catalogue item, "estimated"
 * when the operator entered it from a supplier listing. Measured figures carry
 * no badge.
 */
function AssumedBadge({
  show,
  item,
  partly = false,
}: {
  show: boolean
  item: ConsumableTypeResponse
  /** Some of the figures in the cell are measured, some are not. */
  partly?: boolean
}) {
  if (!show) return null
  const fromCatalogue = !!item.from_catalogue
  const word = fromCatalogue ? 'default' : 'estimated'
  return (
    <Badge
      variant="outline"
      className="ml-1 px-1 py-0 text-[10px]"
      title={
        (fromCatalogue ? 'A catalogue default, not measured' : 'Estimated, not measured') +
        (partly ? ' (some of these sizes are measured)' : '')
      }
    >
      {partly ? `partly ${word}` : word}
    </Badge>
  )
}

function isAssumed(item: ConsumableTypeResponse, field: string): boolean {
  return item.packaging_provenance?.[field] === 'assumed'
}

function sizeCell(item: ConsumableTypeResponse) {
  if (item.packaging_kind === 'void_fill') {
    if (!item.fill_volume_ml) return '—'
    return (
      <>
        {item.fill_volume_ml} ml
        <AssumedBadge item={item} show={isAssumed(item, 'fill_volume_ml')} />
      </>
    )
  }
  if (item.packaging_kind === 'wrap') return '—'
  if (!item.inner_length_mm || !item.inner_width_mm || !item.inner_height_mm) return '—'
  const sides = ['inner_length_mm', 'inner_width_mm', 'inner_height_mm'].map((f) =>
    isAssumed(item, f),
  )
  const assumed = sides.some(Boolean)
  const partly = assumed && !sides.every(Boolean)
  return (
    <>
      {item.inner_length_mm} × {item.inner_width_mm} × {item.inner_height_mm} mm
      {item.packaging_kind === 'mailer' && (
        <span className="text-muted-foreground"> (max thickness)</span>
      )}
      <AssumedBadge item={item} show={assumed} partly={partly} />
    </>
  )
}

function figure(
  item: ConsumableTypeResponse,
  field: 'wall_mm' | 'empty_weight_grams',
  unit: string,
) {
  const value = item[field]
  if (!value) return '—'
  return (
    <>
      {value} {unit}
      <AssumedBadge item={item} show={isAssumed(item, field)} />
    </>
  )
}

export function PackagingList() {
  const { user } = useAuth()
  const canEdit = canEditOperationalFigures(user)
  const { currency } = useCurrency()
  const { carriers } = useCarriers()
  const [addKind, setAddKind] = useState<PackagingKind | null>(null)
  const [catalogueOpen, setCatalogueOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['consumables', packagingListParams],
    queryFn: () => consumablesApi.list(packagingListParams),
  })
  const items = data?.consumables ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Packaging</h1>
          <p className="text-muted-foreground">
            Boxes, mailers, void fill and wrap: what the packaging advisor suggests and every
            margin costs.
          </p>
        </div>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setCatalogueOpen(true)}>
              <Library className="mr-2 h-4 w-4" />
              Add standard packaging
            </Button>
            {PACKAGING_KINDS.map((kind) => (
              <Button key={kind} onClick={() => setAddKind(kind)}>
                <Plus className="mr-2 h-4 w-4" />
                Add {PACKAGING_KIND_LABELS[kind].toLowerCase()}
              </Button>
            ))}
          </div>
        )}
      </div>

      <CatalogueNotice part="packaging" carriers={carriers?.carriers} />

      <Card>
        <CardHeader>
          <CardTitle>Your packaging</CardTitle>
          <CardDescription>
            Sizes are inner sizes; a mailer&apos;s height is its maximum thickness.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading packaging…</p>
          ) : isError ? (
            <p className="text-sm text-destructive">Error loading packaging</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="packaging-empty">
              No packaging yet.{canEdit ? ' Add the standard catalogue or your own box.' : ''}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Wall</TableHead>
                  <TableHead>Empty weight</TableHead>
                  <TableHead className="text-right">Stock</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead>Fits</TableHead>
                  <TableHead>Used by</TableHead>
                  {canEdit && <TableHead className="text-right">Actions</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => {
                  const isContainer =
                    item.packaging_kind === 'box' || item.packaging_kind === 'mailer'
                  return (
                    <TableRow key={item.id} data-testid={`packaging-row-${item.sku}`}>
                      <TableCell>
                        <div className="font-medium">{item.name}</div>
                        <div className="text-xs text-muted-foreground">{item.sku}</div>
                        {item.packaging_incomplete && (
                          <Badge
                            variant="outline"
                            className="mt-1 border-warning text-warning"
                            title="The advisor needs all three inner sizes"
                          >
                            <AlertTriangle className="mr-1 h-3 w-3" />
                            Incomplete: inner size missing
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {item.packaging_kind ? PACKAGING_KIND_LABELS[item.packaging_kind] : '—'}
                      </TableCell>
                      <TableCell>{sizeCell(item)}</TableCell>
                      <TableCell>{isContainer ? figure(item, 'wall_mm', 'mm') : '—'}</TableCell>
                      <TableCell>{figure(item, 'empty_weight_grams', 'g')}</TableCell>
                      <TableCell className="text-right">
                        {item.quantity_on_hand} {item.unit_of_measure}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatMoney(item.current_cost_per_unit, currency.symbol)}
                        <AssumedBadge item={item} show={item.cost_provenance === 'assumed'} />
                      </TableCell>
                      <TableCell className="text-xs" data-testid="fits-services">
                        {isContainer && item.fits_services && item.fits_services.length > 0
                          ? item.fits_services
                              .map((key) => serviceLabel(key, carriers?.carriers))
                              .join(', ')
                          : '—'}
                      </TableCell>
                      <TableCell className="text-xs">
                        {item.used_by_products && item.used_by_products.length > 0
                          ? item.used_by_products.map((p) => p.name).join(', ')
                          : '—'}
                      </TableCell>
                      {canEdit && (
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Edit ${item.name}`}
                            onClick={() => setEditingId(item.id)}
                          >
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Delete ${item.name}`}
                            onClick={() => setDeletingId(item.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <AddConsumableDialog
        open={addKind !== null}
        onOpenChange={(open) => {
          if (!open) setAddKind(null)
        }}
        presetKind={addKind ?? undefined}
        packagingOnly
      />
      <AddCatalogueDialog open={catalogueOpen} onOpenChange={setCatalogueOpen} />
      <EditConsumableDialog
        open={editingId !== null}
        onOpenChange={(open) => {
          if (!open) setEditingId(null)
        }}
        consumableId={editingId}
      />
      <DeleteConsumableDialog
        open={deletingId !== null}
        onOpenChange={(open) => {
          if (!open) setDeletingId(null)
        }}
        consumableId={deletingId}
      />
    </div>
  )
}
