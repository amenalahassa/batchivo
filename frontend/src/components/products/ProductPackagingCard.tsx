/**
 * ProductPackagingCard -- a product's dimensions, fragility and packaging (feature 003).
 *
 * One card for the product and each of its size variants: the dimensions
 * editor, the box suggestions, and the warnings computed on read -- an
 * accepted box the item no longer fits (FR-024), and a size whose packaging
 * the cost breakdown does not use (FR-039).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, Box, Info } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { serviceLabel } from '@/components/packaging/serviceLabels'
import { useCarriers } from '@/hooks/usePostageCatalogue'
import { consumablesApi } from '@/lib/api/consumables'
import { updateProduct, type ProductDetail } from '@/lib/api/products'
import { DimensionsEditor } from './DimensionsEditor'
import { PackagingSuggestions } from './PackagingSuggestions'

const DOES_NOT_FIT = 'accepted_packaging_does_not_fit'
const NOT_COSTED = 'variant_packaging_not_costed'

function DoesNotFit() {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      The accepted packaging no longer fits this item at the clearance in force.
    </div>
  )
}

const SHOP_DEFAULT = '__shop_default__'

/**
 * The product's postage service override (spec 006, FR-019): only the
 * services whose size limits take the product's box are offered. A saved
 * service that no longer takes the box is named, because the margin then
 * falls back to the cheapest service that fits.
 */
function PostageServiceSelect({ product, canEdit }: ProductPackagingCardProps) {
  const queryClient = useQueryClient()
  const { carriers } = useCarriers()
  const containerId = product.packaging_consumable_id ?? null
  const { data: container } = useQuery({
    queryKey: ['consumables', 'detail', containerId],
    queryFn: () => consumablesApi.get(containerId as string),
    enabled: !!containerId,
  })
  const save = useMutation({
    mutationFn: (service: string | null) =>
      updateProduct(product.id, { postage_service: service }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product', product.id] })
      queryClient.invalidateQueries({ queryKey: ['pricing'] })
    },
  })

  if (!containerId) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="postage-service-none">
        Accept a box or mailer to choose the postage service it ships by.
      </p>
    )
  }
  const fits = container?.fits_services ?? []
  const preferred = product.postage_service ?? null
  const preferredFits = preferred === null || fits.includes(preferred)
  const labels = carriers?.carriers

  return (
    <div className="space-y-2">
      <Label htmlFor={`postage-service-${product.id}`}>Postage service</Label>
      <Select
        value={preferred ?? SHOP_DEFAULT}
        disabled={!canEdit || save.isPending}
        onValueChange={(value) => save.mutate(value === SHOP_DEFAULT ? null : value)}
      >
        <SelectTrigger id={`postage-service-${product.id}`} aria-label="Postage service">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={SHOP_DEFAULT}>Shop default</SelectItem>
          {fits.map((key) => (
            <SelectItem key={key} value={key}>
              {serviceLabel(key, labels)}
            </SelectItem>
          ))}
          {preferred && !preferredFits && (
            <SelectItem value={preferred}>{serviceLabel(preferred, labels)}</SelectItem>
          )}
        </SelectContent>
      </Select>
      {preferred && !preferredFits && (
        <p role="status" className="flex items-start gap-1 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {serviceLabel(preferred, labels)} does not take this product&apos;s box; the margin
          uses the cheapest service that fits.
        </p>
      )}
      {fits.length === 0 && container && (
        <p className="text-xs text-muted-foreground">
          No carrier service&apos;s size limits take this box; the shop default applies.
        </p>
      )}
    </div>
  )
}

interface ProductPackagingCardProps {
  product: ProductDetail
  canEdit: boolean
}

export function ProductPackagingCard({ product, canEdit }: ProductPackagingCardProps) {
  const queryClient = useQueryClient()
  const fragile = useMutation({
    mutationFn: (isFragile: boolean) => updateProduct(product.id, { is_fragile: isFragile }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product', product.id] })
      queryClient.invalidateQueries({ queryKey: ['packaging', 'suggestions', product.id] })
    },
  })

  const anchor = `dimensions-${product.id}`

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Box className="h-5 w-5" />
          Dimensions & Packaging
        </CardTitle>
        <CardDescription>
          The item's size, and the stocked box or mailer it fits in. The packaging cost is the
          cost breakdown's line for the accepted box. Boxes and mailers are kept on the{' '}
          <Link to="/packaging" className="underline underline-offset-2">
            Packaging page
          </Link>
          .
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex items-center gap-2">
          <Switch
            id={`fragile-${product.id}`}
            checked={!!product.is_fragile}
            disabled={!canEdit || fragile.isPending}
            onCheckedChange={(checked) => fragile.mutate(checked)}
          />
          <Label htmlFor={`fragile-${product.id}`}>Fragile</Label>
          <span className="text-xs text-muted-foreground">
            Uses the fragile clearance and suggests protective wrap.
          </span>
        </div>

        {product.packaging_warnings?.includes(DOES_NOT_FIT) && <DoesNotFit />}

        <section id={anchor} className="space-y-4">
          <DimensionsEditor
            target={{ kind: 'product', productId: product.id }}
            dimensions={product.dimensions}
            canEdit={canEdit}
            title="Product dimensions"
          />
          <PackagingSuggestions
            productId={product.id}
            canEdit={canEdit}
            dimensionsAnchor={anchor}
          />
          <PostageServiceSelect product={product} canEdit={canEdit} />
        </section>

        {(product.variants ?? []).map((variant) => (
          <section
            key={variant.id}
            id={`dimensions-${variant.id}`}
            className="space-y-3 border-t pt-4"
            data-testid={`variant-packaging-${variant.size}`}
          >
            <div className="text-sm font-medium">
              Size {variant.size} <span className="font-mono text-muted-foreground">{variant.sku}</span>
            </div>
            <DimensionsEditor
              target={{ kind: 'variant', productId: product.id, variantId: variant.id }}
              dimensions={variant.dimensions}
              canEdit={canEdit}
              title={`Size ${variant.size} dimensions`}
            />
            <p className="text-sm">
              Packaging:{' '}
              {variant.effective_packaging ? (
                <>
                  {variant.effective_packaging.name}
                  {variant.effective_packaging.quantity > 1 &&
                    ` ×${variant.effective_packaging.quantity}`}
                  {variant.effective_packaging.inherited && (
                    <span className="text-muted-foreground"> (the product's)</span>
                  )}
                </>
              ) : (
                <span className="text-muted-foreground">none accepted</span>
              )}
            </p>
            {variant.packaging_notes.includes(NOT_COSTED) && (
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <Info className="h-3 w-3" />
                Cost breakdown uses the product's packaging
              </p>
            )}
            {variant.packaging_warnings.includes(DOES_NOT_FIT) && <DoesNotFit />}
            <PackagingSuggestions
              productId={product.id}
              variantId={variant.id}
              canEdit={canEdit}
              dimensionsAnchor={`dimensions-${variant.id}`}
            />
          </section>
        ))}
      </CardContent>
    </Card>
  )
}
