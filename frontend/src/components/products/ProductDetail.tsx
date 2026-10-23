/**
 * ProductDetail Component
 *
 * Displays full product information including models composition,
 * per-channel pricing with profit calculations, and cost breakdown.
 * Products are sellable items composed of one or more Models.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import DOMPurify from 'dompurify'
import {
  ArrowLeft,
  Edit,
  Loader2,
  Trash2,
  Package,
  Layers,
  DollarSign,
  Calculator,
  ShoppingCart,
  TrendingUp,
  TrendingDown,
  Minus,
  Clock,
  Box,
  ImageIcon,
  History,
  Scale,
  Ruler,
  RefreshCw,
  ExternalLink,
  CheckCircle,
  AlertCircle,
  CloudUpload,
} from 'lucide-react'

import {
  getProduct,
  deleteProduct,
  syncProductToEtsy,
} from '@/lib/api/products'
import { useCurrency } from '@/hooks/useCurrency'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { ProductModelsEditor } from './ProductModelsEditor'
import { ProductComponentsEditor } from './ProductComponentsEditor'
import { ProductPricingEditor } from './ProductPricingEditor'
import { compareMoney, formatMoney, formatPercent } from '@/lib/money'
import { makeCostOf } from '@/lib/pricing/makeCost'
import { ProductImagesEditor } from './ProductImagesEditor'
import { ProductCategoriesEditor } from './ProductCategoriesEditor'
import { ProductionHistoryTable } from './ProductionHistoryTable'
import { CostBreakdownSection } from '@/components/pricing/CostBreakdownSection'
import { MarginBasisLabel } from '@/components/pricing/MarginBasisLabel'

interface ProductDetailProps {
  productId: string
}

function StatCard({
  label,
  value,
  subValue,
  icon: Icon,
}: {
  label: string
  value: string
  /** A node rather than a string, so a margin can carry its basis badge. */
  subValue?: React.ReactNode
  icon?: React.ElementType
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {Icon && <Icon className="h-4 w-4" />}
        {label}
      </div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      {subValue && <div className="text-xs text-muted-foreground mt-1">{subValue}</div>}
    </div>
  )
}

function DetailItem({ label, value }: { label: string; value: string | React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

export function ProductDetail({ productId }: ProductDetailProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { currency } = useCurrency()
  const currencySymbol = currency.symbol

  const { data: product, isLoading, error } = useQuery({
    queryKey: ['product', productId],
    queryFn: () => getProduct(productId),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteProduct(productId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
      navigate({ to: '/products' })
    },
  })

  const etsySyncMutation = useMutation({
    mutationFn: (force: boolean = false) => syncProductToEtsy(productId, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product', productId] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-3">Loading product...</span>
      </div>
    )
  }

  if (error || !product) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-semibold text-destructive">Error loading product</p>
          <p className="text-sm text-muted-foreground">
            {error ? (error as Error).message : 'Product not found'}
          </p>
        </div>
      </div>
    )
  }

  // The four buckets, as the exact decimal strings the engine sent. They used
  // to be `parseFloat`ed here and formatted from the resulting doubles, which
  // is the one conversion that can make this screen and the breakdown below
  // disagree in the last cent (Constitution IV). Nothing is computed from
  // them, so there is no reason for them to leave string space at all.
  const costBreakdown = product.cost_breakdown
  const modelsCost = costBreakdown?.models_cost ?? null
  const childProductsCost = costBreakdown?.child_products_cost ?? null
  const packagingCost = costBreakdown?.packaging_cost ?? null
  const assemblyCost = costBreakdown?.assembly_cost ?? null
  // Read through the one accessor the three screens share, so the figure
  // shown here, in the list and in the pricing editor is the same one.
  // As the exact decimal string. The `makeCostNumber` float beside it had one
  // remaining reader -- the invented suggested prices -- and went with them.
  const totalMakeCostExact = makeCostOf(product)

  // Check if this is a bundle (has child products)
  const hasChildProducts = (product.child_products?.length || 0) > 0

  // Find best pricing (highest margin), comparing the decimal strings by
  // value. Through `parseFloat` two margins that differ below a double's
  // precision can order the wrong way round, and the result is not a rounding
  // error -- it is this screen naming the wrong channel as the best one.
  const activePricing = product.pricing?.filter((p) => p.is_active) || []
  const bestPricing = activePricing.reduce(
    (best, current) =>
      compareMoney(current.margin_percentage, best?.margin_percentage) > 0 ? current : best,
    activePricing[0] || null
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Button variant="ghost" size="sm" asChild className="h-auto p-0 hover:bg-transparent">
              <Link to="/products">
                <ArrowLeft className="mr-1 h-4 w-4" />
                Products
              </Link>
            </Button>
            <span>/</span>
            <span className="font-mono">{product.sku}</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">{product.name}</h1>
          <div className="flex items-center gap-2 mt-2">
            <Badge
              variant="outline"
              className={
                product.is_active
                  ? 'bg-green-500/10 text-green-600 border-green-200'
                  : 'bg-gray-500/10 text-gray-500 border-gray-200'
              }
            >
              {product.is_active ? 'Active' : 'Inactive'}
            </Badge>
            <Badge variant="outline">
              <Layers className="mr-1 h-3 w-3" />
              {product.models?.length || 0} models
            </Badge>
            {hasChildProducts && (
              <Badge variant="outline" className="bg-blue-500/10 text-blue-600 border-blue-200">
                <Package className="mr-1 h-3 w-3" />
                {product.child_products?.length || 0} bundled
              </Badge>
            )}
            <Badge variant="outline">
              <ShoppingCart className="mr-1 h-3 w-3" />
              {activePricing.length} channels
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" asChild>
            <Link to="/products/$productId/edit" params={{ productId }}>
              <Edit className="mr-2 h-4 w-4" />
              Edit
            </Link>
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="icon">
                <Trash2 className="h-4 w-4" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete Product</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to delete this product? This will set is_active to false.
                  This action can be reversed by editing the product.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Cost Breakdown Stats Grid */}
      <div className={`grid grid-cols-2 gap-4 ${hasChildProducts ? 'md:grid-cols-5' : 'md:grid-cols-4'}`}>
        <StatCard
          icon={Layers}
          label="Models Cost"
          value={formatMoney(modelsCost, currencySymbol)}
          subValue={`${product.models?.length || 0} model${product.models?.length !== 1 ? 's' : ''}`}
        />
        {hasChildProducts && (
          <StatCard
            icon={Package}
            label="Child Products"
            value={formatMoney(childProductsCost, currencySymbol)}
            subValue={`${product.child_products?.length || 0} product${product.child_products?.length !== 1 ? 's' : ''}`}
          />
        )}
        <StatCard
          icon={Box}
          label="Packaging"
          value={formatMoney(packagingCost, currencySymbol)}
        />
        {/*
          The rate was written into this label as "£10/hr" -- the same
          hardcoded figure Tier 0 deleted from the engine, left behind on a
          screen. It belonged to nobody and contradicted the configured rate
          as soon as the operator set one (FR-002). The minutes are a fact
          about the product, so they stay; the rate is the policy's to state,
          and the breakdown below names it with its origin.
        */}
        <StatCard
          icon={Clock}
          label="Assembly"
          value={formatMoney(assemblyCost, currencySymbol)}
          subValue={`${product.assembly_minutes || 0} min`}
        />
        <StatCard
          icon={Calculator}
          label="Total Make Cost"
          value={formatMoney(totalMakeCostExact, currencySymbol)}
        />
      </div>

      {/*
        The itemised make-cost, every line with where its inputs came from and
        when (FR-018, FR-001), and the share of the total that is observed
        rather than assumed (FR-046, SC-004). The stat cards above are a
        summary of four buckets; this is the figure an operator can defend.
      */}
      <CostBreakdownSection
        productId={product.id}
        currencySymbol={currencySymbol}
      />

      {/*
        Three "suggested retail prices" stood here -- make-cost times 2.5,
        divided by 0.60, and times 3.0, computed as JavaScript floats from
        markups nobody configured. They were a second pricing implementation
        on a screen (Constitution III), they ignored every fee, reserve and
        tax the engine accounts for, and an operator had no way to tell that
        the figure beside their real margin was invented. FR-007 is explicit
        that what a customer will pay is a market judgement the system must
        not compute.

        What replaces them is not another number. The solver answers "what
        price reaches this margin" against the price the percentage fees are
        actually charged on (FR-032), and the ladder shows margin across a
        range so the judgement stays the operator's (FR-007) -- both per
        channel, because a price without a channel has no fees. They live
        behind "Find a price" on each row of Sales Channel Pricing below.
      */}
      <p className="text-sm text-muted-foreground">
        To set a price, use <span className="font-medium">Find a price</span> on a
        channel in <span className="font-medium">Sales Channel Pricing</span> below:
        it solves for a target margin against that channel's own fees, or shows
        margin across a ladder of prices.
      </p>

      {/* Pricing Stats Grid */}
      {bestPricing && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            icon={DollarSign}
            label="Best Price"
            value={formatMoney(bestPricing.list_price, currencySymbol)}
            subValue={bestPricing.channel_name}
          />
          <StatCard
            icon={TrendingUp}
            label="Net Revenue"
            value={formatMoney(bestPricing.net_revenue, currencySymbol)}
            subValue={`After ${bestPricing.platform_type} fees`}
          />
          <StatCard
            label="Profit"
            value={formatMoney(bestPricing.profit, currencySymbol)}
            subValue="After all costs"
          />
          {/* FR-031b: a percentage never appears without the basis that
              produced it. This figure is profit over the price the customer
              paid, which is the `customer_total` basis -- stated as data
              rather than left for the reader to assume. */}
          <StatCard
            label="Margin"
            value={formatPercent(bestPricing.margin_percentage)}
            subValue={
              <MarginBasisLabel basis="customer_total" short className="font-normal" />
            }
          />
        </div>
      )}

      {/* Production Cost Variance Analysis (Phase 3) */}
      {costBreakdown?.models_with_actual_cost > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Production Cost Variance
            </CardTitle>
            <CardDescription>
              Comparison of BOM-based theoretical cost vs actual production costs.
              {costBreakdown.models_with_actual_cost < costBreakdown.models_total && (
                <span className="text-amber-600 ml-1">
                  ({costBreakdown.models_with_actual_cost} of {costBreakdown.models_total} models have production data)
                </span>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {(() => {
              // All four are the engine's own figures, kept as the decimal
              // strings it sent. Only `variance` becomes a number, and only to
              // decide which way the arrow points -- the figure beside the
              // arrow is still rendered from the string (Constitution IV).
              const theoreticalCost = totalMakeCostExact
              const actualCost = costBreakdown.total_actual_cost || null
              const variancePct = costBreakdown.cost_variance_percentage || null
              const variance = variancePct === null ? null : compareMoney(variancePct, '0')
              const modelsActualCost = costBreakdown.models_actual_cost || null
              const hasFullData = costBreakdown.models_with_actual_cost === costBreakdown.models_total

              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="rounded-lg border bg-card p-4">
                      <div className="text-sm text-muted-foreground">Theoretical Cost</div>
                      <div className="text-2xl font-bold mt-1">{formatMoney(theoreticalCost, currencySymbol)}</div>
                      <div className="text-xs text-muted-foreground mt-1">BOM-based estimate</div>
                    </div>
                    <div className="rounded-lg border bg-card p-4">
                      <div className="text-sm text-muted-foreground">Models Actual Cost</div>
                      <div className="text-2xl font-bold mt-1">
                        {modelsActualCost !== null ? formatMoney(modelsActualCost, currencySymbol) : 'N/A'}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        From {costBreakdown.models_with_actual_cost} model{costBreakdown.models_with_actual_cost !== 1 ? 's' : ''}
                      </div>
                    </div>
                    {hasFullData && actualCost !== null && (
                      <div className="rounded-lg border bg-card p-4">
                        <div className="text-sm text-muted-foreground">Total Actual Cost</div>
                        <div className="text-2xl font-bold mt-1">{formatMoney(actualCost, currencySymbol)}</div>
                        <div className="text-xs text-muted-foreground mt-1">Including packaging & assembly</div>
                      </div>
                    )}
                    {hasFullData && variance !== null && (
                      <div className={`rounded-lg border p-4 ${variance > 0 ? 'bg-destructive/10 border-destructive/20' : variance < 0 ? 'bg-green-500/10 border-green-500/20' : 'bg-card'}`}>
                        <div className="text-sm text-muted-foreground">Variance</div>
                        <div className={`text-2xl font-bold mt-1 flex items-center gap-1 ${variance > 0 ? 'text-destructive' : variance < 0 ? 'text-green-600' : ''}`}>
                          {variance > 0 ? <TrendingUp className="h-5 w-5" /> : variance < 0 ? <TrendingDown className="h-5 w-5" /> : <Minus className="h-5 w-5" />}
                          {formatPercent(variancePct?.replace(/^-/, '') ?? null)}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          {variance > 0 ? 'Over budget' : variance < 0 ? 'Under budget' : 'On budget'}
                        </div>
                      </div>
                    )}
                  </div>
                  {!hasFullData && (
                    <div className="text-sm text-muted-foreground bg-muted/50 rounded p-3">
                      Complete variance analysis will be available when all {costBreakdown.models_total} models have production cost data.
                    </div>
                  )}
                </div>
              )
            })()}
          </CardContent>
        </Card>
      )}

      {/* Product Details Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Product Details
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {product.description && (
            <div className="pb-3 mb-3 border-b">
              <span className="text-sm text-muted-foreground">Description</span>
              <div
                className="mt-1 prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1"
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(product.description) }}
              />
            </div>
          )}

          <DetailItem label="SKU" value={<span className="font-mono">{product.sku}</span>} />
          <DetailItem label="Units in Stock" value={product.units_in_stock?.toString() || '0'} />
          <DetailItem
            label="Packaging"
            value={
              product.packaging_consumable_name ? (
                <span>
                  {product.packaging_consumable_name}
                  {product.packaging_quantity > 1 && ` ×${product.packaging_quantity}`}
                  <span className="text-muted-foreground ml-1">
                    ({formatMoney(product.cost_breakdown?.packaging_cost, currencySymbol)})
                  </span>
                </span>
              ) : (
                formatMoney(product.packaging_cost, currencySymbol)
              )
            }
          />
          <DetailItem
            label="Assembly Time"
            value={`${product.assembly_minutes || 0} minutes`}
          />

          {/* Product Specifications */}
          {(product.weight_grams || product.size_cm || product.print_time_hours) && (
            <div className="pt-3 mt-3 border-t">
              <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
                <Ruler className="h-4 w-4" />
                Product Specifications
              </div>
              <div className="grid grid-cols-3 gap-4">
                {product.weight_grams && (
                  <div className="flex items-center gap-2">
                    <Scale className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-xs text-muted-foreground">Weight</p>
                      <p className="font-medium">{product.weight_grams}g</p>
                    </div>
                  </div>
                )}
                {product.size_cm && (
                  <div className="flex items-center gap-2">
                    <Ruler className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-xs text-muted-foreground">Size</p>
                      <p className="font-medium">{product.size_cm}cm</p>
                    </div>
                  </div>
                )}
                {product.print_time_hours && (
                  <div className="flex items-center gap-2">
                    <Clock className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-xs text-muted-foreground">Print Time</p>
                      <p className="font-medium">{product.print_time_hours}h</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="pt-3 mt-3 border-t grid grid-cols-2 gap-4 text-xs text-muted-foreground">
            <div>
              <span>Created</span>
              <p className="font-medium text-foreground">
                {new Date(product.created_at).toLocaleDateString()}
              </p>
            </div>
            <div>
              <span>Last Updated</span>
              <p className="font-medium text-foreground">
                {new Date(product.updated_at).toLocaleDateString()}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Product Images */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ImageIcon className="h-5 w-5" />
            Product Images
          </CardTitle>
          <CardDescription>
            Images for shop display. First image is the primary (shown in listings).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProductImagesEditor productId={productId} />
        </CardContent>
      </Card>

      {/* Categories */}
      <ProductCategoriesEditor productId={productId} categories={product.categories || []} />

      {/* Models Composition */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Models Composition
          </CardTitle>
          <CardDescription>
            Models that make up this product with quantities
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProductModelsEditor productId={productId} models={product.models || []} />
        </CardContent>
      </Card>

      {/* Child Products (Bundle Composition) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Bundled Products
          </CardTitle>
          <CardDescription>
            Other products included in this bundle (for sets and combos)
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProductComponentsEditor productId={productId} components={product.child_products || []} />
        </CardContent>
      </Card>

      {/* Per-Channel Pricing */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DollarSign className="h-5 w-5" />
            Sales Channel Pricing
          </CardTitle>
          <CardDescription>
            Prices, fees, and profit by sales channel
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProductPricingEditor
            productId={productId}
            pricing={product.pricing || []}
            makeCost={totalMakeCostExact}
          />
        </CardContent>
      </Card>

      {/* Etsy Sync */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CloudUpload className="h-5 w-5" />
            Etsy Marketplace
          </CardTitle>
          <CardDescription>
            Sync this product to your Etsy shop
          </CardDescription>
        </CardHeader>
        <CardContent>
          {(() => {
            const etsyListing = product.external_listings?.find((l) => l.platform === 'etsy')

            return (
              <div className="space-y-4">
                {/* Sync Status */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {etsyListing ? (
                      <>
                        {etsyListing.sync_status === 'synced' && (
                          <CheckCircle className="h-5 w-5 text-green-500" />
                        )}
                        {etsyListing.sync_status === 'pending' && (
                          <RefreshCw className="h-5 w-5 text-amber-500" />
                        )}
                        {etsyListing.sync_status === 'error' && (
                          <AlertCircle className="h-5 w-5 text-red-500" />
                        )}
                        <div>
                          <p className="font-medium capitalize">{etsyListing.sync_status}</p>
                          {etsyListing.last_synced_at && (
                            <p className="text-xs text-muted-foreground">
                              Last synced: {new Date(etsyListing.last_synced_at).toLocaleString()}
                            </p>
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-muted-foreground">Not synced to Etsy yet</p>
                    )}
                  </div>

                  {etsyListing?.external_url && (
                    <Button variant="outline" size="sm" asChild>
                      <a href={etsyListing.external_url} target="_blank" rel="noopener noreferrer">
                        <ExternalLink className="mr-2 h-4 w-4" />
                        View on Etsy
                      </a>
                    </Button>
                  )}
                </div>

                {/* Sync Button */}
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() => etsySyncMutation.mutate(false)}
                    disabled={etsySyncMutation.isPending || !product.is_active}
                  >
                    {etsySyncMutation.isPending && (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    )}
                    {!etsySyncMutation.isPending && (
                      <CloudUpload className="mr-2 h-4 w-4" />
                    )}
                    {etsyListing ? 'Update on Etsy' : 'Sync to Etsy'}
                  </Button>

                  {etsyListing && (
                    <Button
                      variant="outline"
                      onClick={() => etsySyncMutation.mutate(true)}
                      disabled={etsySyncMutation.isPending}
                    >
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Force Re-sync
                    </Button>
                  )}
                </div>

                {/* Sync Result Message */}
                {etsySyncMutation.isSuccess && (
                  <div className="rounded-md bg-green-50 p-3 text-sm text-green-700">
                    {etsySyncMutation.data.message}
                  </div>
                )}

                {etsySyncMutation.isError && (
                  <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                    Sync failed: {(etsySyncMutation.error as Error).message}
                  </div>
                )}

                {!product.is_active && (
                  <p className="text-sm text-muted-foreground">
                    Activate the product to enable Etsy sync
                  </p>
                )}
              </div>
            )
          })()}
        </CardContent>
      </Card>

      {/* Production History */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5" />
            Production History
          </CardTitle>
          <CardDescription>
            Production runs that include this product's models
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ProductionHistoryTable
            productId={productId}
            modelIds={product.models?.map((m) => m.model_id) || []}
          />
        </CardContent>
      </Card>
    </div>
  )
}
