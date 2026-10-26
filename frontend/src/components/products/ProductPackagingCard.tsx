/**
 * ProductPackagingCard -- a product's dimensions, fragility and packaging (feature 003).
 *
 * One card for the product and each of its size variants: the dimensions
 * editor, the box suggestions, and the warnings computed on read -- an
 * accepted box the item no longer fits (FR-024), and a size whose packaging
 * the cost breakdown does not use (FR-039).
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Box, Info } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
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
          cost breakdown's line for the accepted box.
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
