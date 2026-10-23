/**
 * ModelDetail Component
 *
 * Displays full model information including BOM (materials), components, and cost breakdown.
 * Models are printed items with bill of materials.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft, Edit, Loader2, SlidersHorizontal, Trash2, Package, TrendingUp, TrendingDown, Minus } from 'lucide-react'

import { getModel, deleteModel } from '@/lib/api/models'
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
import { CostBreakdownSection } from '@/components/pricing/CostBreakdownSection'
import { useCurrency } from '@/hooks/useCurrency'
import {
  ZERO,
  compareMoney,
  divideMoney,
  formatMoney,
  formatPercent,
  multiplyMoney,
  subtractMoney,
} from '@/lib/money'
import type { Money } from '@/types/pricing'
import { useAuth } from '@/contexts/AuthContext'
import { canEditOperationalFigures } from '@/lib/pricing/permissions'
import { BOMEditor } from './BOMEditor'
import { ComponentsEditor } from './ComponentsEditor'
import { ModelCostProfileDialog } from './ModelCostProfileDialog'

interface ModelDetailProps {
  modelId: string
}

function StatCard({ label, value, subValue }: { label: string; value: string; subValue?: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
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

export function ModelDetail({ modelId }: ModelDetailProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  // A purge weight and a finishing time are measurements, so a member may
  // record them; a viewer meets the control present and disabled rather than
  // gone, because a figure whose editor vanished is one nobody can explain
  // (FR-007b, FR-007c).
  const canEditProfile = canEditOperationalFigures(user)
  const [costProfileOpen, setCostProfileOpen] = useState(false)
  const { currency } = useCurrency()
  const currencySymbol = currency.symbol

  const { data: model, isLoading, error } = useQuery({
    queryKey: ['model', modelId],
    queryFn: () => getModel(modelId),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteModel(modelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
      navigate({ to: '/models' })
    },
  })

  // Three decimals, because a single printed item's cost is often fractions of
  // a unit. The symbol is the tenant's, not a hardcoded `£`: a cost carries a
  // currency (FR-028), and a figure labelled in the wrong one is worse than an
  // unlabelled one.
  //
  // It renders the decimal string the API sent and never becomes a double. The
  // `parseFloat(...).toFixed(3)` this replaced was the same conversion T143
  // took out of the product screens, and it is how this screen and the
  // breakdown below could disagree in the last fraction of a cent while both
  // reported the same engine figure (Constitution IV, task T151).
  const formatCurrency = (value: Money | null | undefined) =>
    formatMoney(value, currencySymbol, { places: 3 })

  if (isLoading) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-3">Loading model...</span>
      </div>
    )
  }

  if (error || !model) {
    return (
      <div className="flex h-[400px] items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-semibold text-destructive">Error loading model</p>
          <p className="text-sm text-muted-foreground">{error ? (error as Error).message : 'Model not found'}</p>
        </div>
      </div>
    )
  }

  // The four buckets, as the exact decimal strings the engine sent. Nothing is
  // computed from them here, so there is no reason for them to leave string
  // space at all (task T151).
  const costBreakdown = model.cost_breakdown
  const totalCost = costBreakdown?.total_cost ?? null
  const materialsCost = costBreakdown?.material_cost ?? null
  const componentsCost = costBreakdown?.component_cost ?? null
  const laborCost = costBreakdown?.labor_cost ?? null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Button variant="ghost" size="sm" asChild className="h-auto p-0 hover:bg-transparent">
              <Link to="/models">
                <ArrowLeft className="mr-1 h-4 w-4" />
                Models
              </Link>
            </Button>
            <span>/</span>
            <span className="font-mono">{model.sku}</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">{model.name}</h1>
          <div className="flex items-center gap-2 mt-2">
            <Badge variant={model.is_active ? 'default' : 'secondary'}>
              {model.is_active ? 'Active' : 'Inactive'}
            </Badge>
            {model.category && (
              <Badge variant="outline">{model.category}</Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/*
            The door to the figures that decide what printing this costs. Until
            T147 there was none at all: waste, yield, the failure mode and the
            labour split were columns the engine read and nothing could write,
            so every item in every tenant was costed as though nothing is
            purged and nothing ever fails (FR-007b, FR-009, FR-012, FR-015a).
          */}
          <Button
            variant="outline"
            onClick={() => setCostProfileOpen(true)}
            data-testid="open-cost-profile"
          >
            <SlidersHorizontal className="mr-2 h-4 w-4" />
            Cost profile
          </Button>
          <Button variant="outline" asChild>
            <Link to="/models/$modelId/edit" params={{ modelId }}>
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
                <AlertDialogTitle>Delete Model</AlertDialogTitle>
                <AlertDialogDescription>
                  Are you sure you want to delete this model? This will set is_active to false.
                  This action can be reversed by editing the model.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
                  {deleteMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {/* Cost Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Materials Cost"
          value={formatCurrency(materialsCost)}
          subValue={`${model.materials?.length || 0} materials`}
        />
        <StatCard
          label="Components Cost"
          value={formatCurrency(componentsCost)}
          subValue={`${model.components?.length || 0} components`}
        />
        <StatCard
          label="Labor Cost"
          value={formatCurrency(laborCost)}
          // Hours are a duration, not money: a float is the right type for one,
          // and `money.ts` is deliberately only for amounts and rates.
          subValue={`${parseFloat(model.labor_hours || '0').toFixed(1)}h labor`}
        />
        <StatCard
          label="Total Cost"
          value={formatCurrency(totalCost)}
          subValue={
            costBreakdown
              ? `+${formatPercent(model.overhead_percentage ?? '0', { places: 0, undefinedLabel: '0%' })} overhead`
              : undefined
          }
        />
      </div>

      {/*
        The engine's own breakdown for this printed item: material, waste,
        machine occupancy, the four labour components, overhead and the failure
        premium, each line naming its origin and date (FR-018, FR-001) and the
        premium naming the failure mode that produced it (FR-015e). The cards
        above total four buckets; this is where the machine time and the yield
        become visible.
      */}
      <CostBreakdownSection modelId={model.id} currencySymbol={currencySymbol} />

      {/*
        A "Recommended Price", an "Alternative Price" and a "Profit at 2.5×"
        stood here -- make-cost times 2.5 and divided by 0.60, computed as
        JavaScript floats from markups nobody configured. They were the same
        three tiles T140 removed from the product screen, left standing here
        directly above the engine's own breakdown, so one screen offered two
        answers (Constitution III). They ignored every fee, reserve, postage
        figure and tax the engine accounts for, and nothing told the operator
        that the number beside their real cost was invented. FR-007 is explicit
        that what a customer will pay is a market judgement the system must not
        compute as a single figure.

        A model is not priced: a price belongs to a product on a channel,
        because a price without a channel has no fees. So the pointer goes
        there rather than inventing a model-level price (task T146).
      */}
      <p className="text-sm text-muted-foreground">
        A model carries a cost, not a price. To price what this model goes into,
        open the product that uses it and choose{' '}
        <span className="font-medium">Find a price</span> on a channel in{' '}
        <span className="font-medium">Sales Channel Pricing</span>: it solves for
        a target margin against that channel's own fees, or shows margin across a
        ladder of prices.
      </p>

      {/* Production Cost Analysis (Phase 2) */}
      {model.production_cost_count > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Production Cost Analysis
            </CardTitle>
            <CardDescription>
              Comparison of theoretical (BOM-based) cost vs actual production costs from {model.production_cost_count} completed unit{model.production_cost_count !== 1 ? 's' : ''}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {(() => {
              // Actual against theoretical, in string space. Through
              // `parseFloat` a run that matched plan exactly can come out at
              // -1.4e-17 and render as an overrun, and the arrow beside it
              // points the wrong way -- which is not a rounding error, it is
              // the screen reporting the wrong finding (task T151).
              const actualCost = model.actual_production_cost ?? null
              const difference = subtractMoney(actualCost, totalCost)
              // No theoretical cost is not "on budget", it is nothing to
              // compare against, so the percentage has no answer (FR-019).
              const variance =
                compareMoney(totalCost, ZERO) > 0
                  ? multiplyMoney(divideMoney(difference, totalCost as Money, 6) ?? ZERO, 100)
                  : null
              const direction = variance === null ? 0 : compareMoney(variance, ZERO)
              const isOverBudget = direction > 0
              const isUnderBudget = direction < 0
              const varianceAbs = variance === null ? null : variance.replace(/^-/, '')

              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-4">
                    <div className="rounded-lg border bg-card p-4">
                      <div className="text-sm text-muted-foreground">Theoretical Cost</div>
                      <div className="text-2xl font-bold mt-1">{formatCurrency(totalCost)}</div>
                      <div className="text-xs text-muted-foreground mt-1">BOM-based estimate</div>
                    </div>
                    <div className="rounded-lg border bg-card p-4">
                      <div className="text-sm text-muted-foreground">Actual Cost</div>
                      <div className="text-2xl font-bold mt-1">{formatCurrency(actualCost)}</div>
                      <div className="text-xs text-muted-foreground mt-1">Rolling average</div>
                    </div>
                    <div className={`rounded-lg border p-4 ${isOverBudget ? 'bg-destructive/10 border-destructive/20' : isUnderBudget ? 'bg-green-500/10 border-green-500/20' : 'bg-card'}`}>
                      <div className="text-sm text-muted-foreground">Variance</div>
                      <div className={`text-2xl font-bold mt-1 flex items-center gap-1 ${isOverBudget ? 'text-destructive' : isUnderBudget ? 'text-green-600' : ''}`}>
                        {isOverBudget ? <TrendingUp className="h-5 w-5" /> : isUnderBudget ? <TrendingDown className="h-5 w-5" /> : <Minus className="h-5 w-5" />}
                        {formatPercent(varianceAbs, { undefinedLabel: '—' })}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {variance === null
                          ? 'No theoretical cost to compare'
                          : isOverBudget
                            ? 'Over budget'
                            : isUnderBudget
                              ? 'Under budget'
                              : 'On budget'}
                      </div>
                    </div>
                  </div>
                  {model.production_cost_updated_at && (
                    <div className="text-xs text-muted-foreground">
                      Last updated: {new Date(model.production_cost_updated_at).toLocaleDateString()} at {new Date(model.production_cost_updated_at).toLocaleTimeString()}
                    </div>
                  )}
                </div>
              )
            })()}
          </CardContent>
        </Card>
      )}

      <ModelCostProfileDialog
        open={costProfileOpen}
        onOpenChange={setCostProfileOpen}
        modelId={modelId}
        modelName={model.name}
        canEdit={canEditProfile}
      />

      {/* Model Details Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" />
            Model Details
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {model.description && (
            <div className="pb-3 mb-3 border-b">
              <span className="text-sm text-muted-foreground">Description</span>
              <p className="mt-1 whitespace-pre-wrap">{model.description}</p>
            </div>
          )}

          <DetailItem label="SKU" value={<span className="font-mono">{model.sku}</span>} />
          {model.designer && <DetailItem label="Designer" value={model.designer} />}
          {model.source && <DetailItem label="Source" value={model.source} />}
          {model.machine && <DetailItem label="Machine" value={model.machine} />}
          {model.print_time_minutes && (
            <DetailItem
              label="Print Time"
              value={`${Math.floor(model.print_time_minutes / 60)}h ${model.print_time_minutes % 60}m`}
            />
          )}
          <DetailItem label="Units in Stock" value={model.units_in_stock?.toString() || '0'} />

          <div className="pt-3 mt-3 border-t grid grid-cols-2 gap-4 text-xs text-muted-foreground">
            <div>
              <span>Created</span>
              <p className="font-medium text-foreground">{new Date(model.created_at).toLocaleDateString()}</p>
            </div>
            <div>
              <span>Last Updated</span>
              <p className="font-medium text-foreground">{new Date(model.updated_at).toLocaleDateString()}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Bill of Materials */}
      <Card>
        <CardHeader>
          <CardTitle>Bill of Materials (Per Unit)</CardTitle>
          <CardDescription>
            Filament weights for a single unit. Purge tower and flush waste are tracked when creating production runs.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Show per-plate calculation if prints_per_plate > 1 */}
          {model.prints_per_plate && model.prints_per_plate > 1 && model.materials && model.materials.length > 0 && (
            <div className="mb-4 rounded-lg bg-muted/50 p-3 text-sm">
              <div className="font-medium">Plate Calculation</div>
              <div className="text-muted-foreground mt-1">
                Per Unit:{' '}
                <span className="font-medium text-foreground">
                  {model.materials.reduce((sum, m) => sum + parseFloat(m.weight_grams || '0'), 0).toFixed(1)}g
                </span>
                {' · '}
                Per Plate (×{model.prints_per_plate}):{' '}
                <span className="font-medium text-foreground">
                  {(model.materials.reduce((sum, m) => sum + parseFloat(m.weight_grams || '0'), 0) * model.prints_per_plate).toFixed(1)}g
                </span>
                <span className="text-xs ml-1">(model only, + waste when running)</span>
              </div>
            </div>
          )}
          <BOMEditor modelId={modelId} materials={model.materials || []} />
        </CardContent>
      </Card>

      {/* Components */}
      <Card>
        <CardHeader>
          <CardTitle>Components</CardTitle>
          <CardDescription>Non-material components (magnets, inserts, screws, etc.)</CardDescription>
        </CardHeader>
        <CardContent>
          <ComponentsEditor modelId={modelId} components={model.components || []} />
        </CardContent>
      </Card>
    </div>
  )
}
