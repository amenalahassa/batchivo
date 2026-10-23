/**
 * WizardReview Component
 *
 * Step 5: Review before creating the product.
 * Summary of all selections with edit buttons.
 */

import { Pencil, Layers, Package, Tags, Box } from 'lucide-react'

import { useCurrency } from '@/hooks/useCurrency'
import { formatMoney, multiplyMoney, sumMoney } from '@/lib/money'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'

import type { WizardData } from './index'

interface WizardReviewProps {
  wizardData: WizardData
  onEditStep: (step: number) => void
}

export function WizardReview({ wizardData, onEditStep }: WizardReviewProps) {
  const { currency } = useCurrency()
  const symbol = currency.symbol

  // Each model's contribution, exactly: the cost the engine reported for that
  // model times the quantity this product carries. Summed in string space,
  // because `parseFloat(a) * n` summed over a few models is how a subtotal
  // reads a penny off the sum of the lines above it (FR-047, task T151).
  const modelLineTotal = (model: { total_cost?: string | null; quantity: number }) =>
    multiplyMoney(model.total_cost ?? '0', model.quantity)
  const modelsCost = sumMoney(wizardData.selectedModels.map(modelLineTotal))

  // The packaging figure as the operator typed it. Nothing is derived from it
  // here.
  const packagingCost = wizardData.packagingCost || '0'

  return (
    <div className="space-y-4">
      <div className="text-center mb-6">
        <h3 className="text-lg font-semibold">Review Your Product</h3>
        <p className="text-sm text-muted-foreground">
          Please review the details before creating your product
        </p>
      </div>

      {/* Models Section */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Layers className="h-4 w-4" />
              Models
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEditStep(0)}
              className="h-8"
            >
              <Pencil className="h-3 w-3 mr-1" />
              Edit
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {wizardData.selectedModels.length === 0 ? (
            <p className="text-sm text-muted-foreground">No models selected</p>
          ) : (
            <div className="space-y-2">
              {wizardData.selectedModels.map((model) => (
                <div key={model.id} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span>{model.name}</span>
                    <Badge variant="outline" className="text-xs">
                      x{model.quantity}
                    </Badge>
                  </div>
                  <span className="font-medium">
                    {formatMoney(modelLineTotal(model), symbol)}
                  </span>
                </div>
              ))}
              <Separator className="my-2" />
              <div className="flex justify-between font-medium">
                <span>Models Total</span>
                <span>{formatMoney(modelsCost, symbol)}</span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Product Details Section */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Package className="h-4 w-4" />
              Product Details
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEditStep(1)}
              className="h-8"
            >
              <Pencil className="h-3 w-3 mr-1" />
              Edit
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-0 space-y-2">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-muted-foreground">SKU:</span>
              <span className="ml-2 font-mono">{wizardData.sku || '-'}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Name:</span>
              <span className="ml-2">{wizardData.name || '-'}</span>
            </div>
          </div>
          {wizardData.description && (
            <div className="text-sm">
              <span className="text-muted-foreground">Description:</span>
              <div
                className="mt-1 text-xs text-muted-foreground line-clamp-2"
                dangerouslySetInnerHTML={{ __html: wizardData.description }}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Categories Section */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Tags className="h-4 w-4" />
              Categories
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEditStep(2)}
              className="h-8"
            >
              <Pencil className="h-3 w-3 mr-1" />
              Edit
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {wizardData.selectedCategories.length === 0 ? (
            <p className="text-sm text-muted-foreground">No categories selected</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {wizardData.selectedCategories.map((category) => (
                <Badge key={category.id} variant="secondary">
                  {category.name}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Packaging Section */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Box className="h-4 w-4" />
              Packaging & Assembly
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onEditStep(3)}
              className="h-8"
            >
              <Pencil className="h-3 w-3 mr-1" />
              Edit
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-0 space-y-2">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-muted-foreground">Packaging Cost:</span>
              <span className="ml-2">{formatMoney(packagingCost, symbol)}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Assembly:</span>
              <span className="ml-2">{wizardData.assemblyMinutes} min</span>
            </div>
          </div>
          {/*
            A "Labor Cost" line stood here at `(assemblyMinutes / 60) * 10` --
            the same labour rate hardcoded to 10.0 that Tier 0 deleted from
            `Product.calculate_make_cost`, back on a screen. A rate the operator
            configured is the rate the system must use (Constitution IV), and
            the assembly minutes below are the input the engine costs at it.
          */}
        </CardContent>
      </Card>

      {/*
        An "Estimated Total Cost" of models plus packaging plus that invented
        labour figure stood here. It was a second make-cost implementation in
        the browser (Constitution III, FR-048): no machine occupancy, no purge
        waste, no yield premium, no overhead absorption, and labour at a rate
        nobody set -- so the wizard's last screen and the product's own
        breakdown disagreed from the moment the product existed.

        What replaces it is the inputs, not another total. The make-cost is the
        engine's, computed on demand from these figures and the policy in force
        (Constitution V), and it is on the product the moment this wizard
        finishes (task T151).
      */}
      <Card className="bg-primary/5 border-primary/20">
        <CardContent className="py-4 space-y-1">
          <h4 className="font-semibold">Make-cost is computed after creation</h4>
          <p className="text-xs text-muted-foreground">
            The figures above are the inputs. The itemised make-cost — machine
            occupancy, purge waste, the failure premium, overhead and labour at
            your configured rates — appears on the product once it exists, with
            the origin of every line.
          </p>
        </CardContent>
      </Card>

      <p className="text-sm text-muted-foreground text-center">
        Click "Create Product" to finalize. You can add more details (pricing, images) after creation.
      </p>
    </div>
  )
}
