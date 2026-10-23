/**
 * ProductionHistoryTable Component
 *
 * Displays production runs that include models from a specific product.
 * Shows run details, success rates, and cost variance.
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { format, parseISO, subDays } from 'date-fns'
import {
  ArrowUpRight,
  Calendar,
  CheckCircle,
  Clock,
  Loader2,
  TrendingDown,
  TrendingUp,
  XCircle,
} from 'lucide-react'
import { listProductionRuns, formatStatus, formatDuration } from '@/lib/api/production-runs'
import { useCurrency } from '@/hooks/useCurrency'
import {
  ZERO,
  compareMoney,
  divideMoney,
  formatPercent,
  multiplyMoney,
  subtractMoney,
  sumMoney,
} from '@/lib/money'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { Money } from '@/types/pricing'
import type { ProductionRunDetail, ProductionRunStatus } from '@/types/production-run'

interface ProductionHistoryTableProps {
  productId: string
  modelIds: string[]
}

type DateRangeOption = '7d' | '30d' | '90d' | 'all'

interface ProductRunSummary {
  run: ProductionRunDetail
  itemQuantity: number
  successfulQuantity: number
  failedQuantity: number
  successRate: number
  /**
   * Exact decimal strings, and `null` where nothing was recorded.
   *
   * Both were `number` and both were wrong (task T193). `estimated_total_cost`
   * is `Optional[Decimal]` on the API, so it arrives as a JSON *string*, and
   * `0 + "12.50" + "8.00"` is the string `"012.508.00"` — every cost column on
   * this table was broken for any run with more than one costed item.
   *
   * `actualCost` was worse than broken: it was
   * `estimated * (1 + variance/100) * (successRate/100)`, an estimate scaled
   * by a *weight* variance and a yield. The recorded actuals live on the run
   * (`actual_cost_per_unit`, written by
   * `ProductionRunService.record_actual_unit_costs`) and are what
   * `ProductionRunDetail` renders, so the two screens answered differently for
   * one run (Constitution III and IV, SC-008, FR-040).
   *
   * `null` rather than zero, because a cost nobody recorded and a cost of
   * nothing are different facts and showing the second for the first is what
   * FR-019 forbids.
   */
  estimatedCost: Money | null
  actualCost: Money | null
}

function getStatusBadgeVariant(status: ProductionRunStatus) {
  switch (status) {
    case 'completed':
      return 'success'
    case 'in_progress':
      return 'default'
    case 'failed':
      return 'destructive'
    case 'cancelled':
      return 'secondary'
    default:
      return 'secondary'
  }
}

function getStatusIcon(status: ProductionRunStatus) {
  switch (status) {
    case 'completed':
      return <CheckCircle className="h-3 w-3" />
    case 'in_progress':
      return <Clock className="h-3 w-3" />
    case 'failed':
    case 'cancelled':
      return <XCircle className="h-3 w-3" />
    default:
      return null
  }
}

export function ProductionHistoryTable({ productId, modelIds }: ProductionHistoryTableProps) {
  const [dateRange, setDateRange] = useState<DateRangeOption>('30d')
  const [statusFilter, setStatusFilter] = useState<ProductionRunStatus | 'all'>('all')
  const { formatCurrency } = useCurrency()

  // Fetch all production runs (we filter client-side by model)
  const { data, isLoading, error } = useQuery({
    queryKey: ['production-runs-for-product', productId, dateRange],
    queryFn: () => {
      const startDate =
        dateRange === 'all'
          ? undefined
          : format(subDays(new Date(), parseInt(dateRange)), 'yyyy-MM-dd')
      return listProductionRuns({
        start_date: startDate,
        limit: 500,
      })
    },
  })

  // Filter and summarize runs containing this product's models
  const productRuns = useMemo<ProductRunSummary[]>(() => {
    if (!data?.runs || modelIds.length === 0) return []

    const modelIdSet = new Set(modelIds)

    return data.runs
      .filter((run) => {
        // Check if run has any items for this product's models
        const hasProductItems = (run as ProductionRunDetail).items?.some(
          (item) => item.model_id && modelIdSet.has(item.model_id)
        )
        // Apply status filter
        if (statusFilter !== 'all' && run.status !== statusFilter) {
          return false
        }
        return hasProductItems
      })
      .map((run) => {
        const runDetail = run as ProductionRunDetail
        // Get items for this product's models
        const productItems =
          runDetail.items?.filter((item) => item.model_id && modelIdSet.has(item.model_id)) || []

        const itemQuantity = productItems.reduce((sum, item) => sum + item.quantity, 0)
        const successfulQuantity = productItems.reduce(
          (sum, item) => sum + item.successful_quantity,
          0
        )
        const failedQuantity = productItems.reduce((sum, item) => sum + item.failed_quantity, 0)
        const successRate =
          itemQuantity > 0 ? (successfulQuantity / itemQuantity) * 100 : 0

        // The BOM estimate captured when each print was created, summed
        // exactly. A run where no item carries one has an unknown estimate,
        // which reads as a dash rather than as £0.00 (FR-019).
        const estimates = productItems
          .map((item) => item.estimated_total_cost)
          .filter((cost): cost is Money => cost != null)
        const estimatedCost = estimates.length > 0 ? sumMoney(estimates) : null

        // The recorded actual, not a figure derived from the estimate.
        //
        // `actual_cost_per_unit` is written per unit by
        // `record_actual_unit_costs` once a run completes, so the cost of what
        // this product actually yielded is that times the units that
        // succeeded. The estimate above is for what was *planned*; a run that
        // lost parts therefore shows a lower actual than estimate, which is
        // the yield showing up in the cost rather than an error.
        const actuals = productItems
          .filter((item) => item.actual_cost_per_unit != null)
          .map((item) => multiplyMoney(item.actual_cost_per_unit, item.successful_quantity))
        const actualCost = actuals.length > 0 ? sumMoney(actuals) : null

        return {
          run: runDetail,
          itemQuantity,
          successfulQuantity,
          failedQuantity,
          successRate,
          estimatedCost,
          actualCost,
        }
      })
      .sort((a, b) => new Date(b.run.started_at).getTime() - new Date(a.run.started_at).getTime())
  }, [data?.runs, modelIds, statusFilter])

  // Calculate summary statistics
  const summaryStats = useMemo(() => {
    const empty = {
      totalRuns: 0,
      totalQuantity: 0,
      averageSuccessRate: 0,
      totalEstimatedCost: null as Money | null,
      totalActualCost: null as Money | null,
      costVariance: null as Money | null,
    }
    if (productRuns.length === 0) return empty

    const totalRuns = productRuns.length
    const totalQuantity = productRuns.reduce((sum, pr) => sum + pr.itemQuantity, 0)
    const totalSuccessful = productRuns.reduce((sum, pr) => sum + pr.successfulQuantity, 0)
    const averageSuccessRate = totalQuantity > 0 ? (totalSuccessful / totalQuantity) * 100 : 0

    // Only the runs that have a figure contribute one, so a single costed run
    // among ten uncosted ones reports its own cost rather than being averaged
    // against nine zeroes.
    const estimated = productRuns
      .map((pr) => pr.estimatedCost)
      .filter((cost): cost is Money => cost != null)
    const actual = productRuns
      .map((pr) => pr.actualCost)
      .filter((cost): cost is Money => cost != null)

    const totalEstimatedCost = estimated.length > 0 ? sumMoney(estimated) : null
    const totalActualCost = actual.length > 0 ? sumMoney(actual) : null

    // A variance needs both sides and a non-zero denominator. Without them it
    // is undefined, which is a dash — reporting 0% would say "on plan" about a
    // comparison that was never made.
    const costVariance =
      totalEstimatedCost != null &&
      totalActualCost != null &&
      compareMoney(totalEstimatedCost, ZERO) > 0
        ? divideMoney(
            multiplyMoney(subtractMoney(totalActualCost, totalEstimatedCost), 100),
            totalEstimatedCost,
            1
          )
        : null

    return {
      totalRuns,
      totalQuantity,
      averageSuccessRate,
      totalEstimatedCost,
      totalActualCost,
      costVariance,
    }
  }, [productRuns])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        <span className="ml-2 text-muted-foreground">Loading production history...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-8 text-destructive">
        <p>Error loading production history</p>
        <p className="text-sm text-muted-foreground">{(error as Error).message}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex gap-2">
          <Select value={dateRange} onValueChange={(v) => setDateRange(v as DateRangeOption)}>
            <SelectTrigger className="w-[140px]">
              <Calendar className="h-4 w-4 mr-2" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">Last 7 days</SelectItem>
              <SelectItem value="30d">Last 30 days</SelectItem>
              <SelectItem value="90d">Last 90 days</SelectItem>
              <SelectItem value="all">All time</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={statusFilter}
            onValueChange={(v) => setStatusFilter(v as ProductionRunStatus | 'all')}
          >
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All status</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="in_progress">In Progress</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Summary stats */}
        <div className="flex gap-4 text-sm">
          <div className="text-center">
            <p className="text-muted-foreground">Runs</p>
            <p className="font-semibold">{summaryStats.totalRuns}</p>
          </div>
          <div className="text-center">
            <p className="text-muted-foreground">Units</p>
            <p className="font-semibold">{summaryStats.totalQuantity}</p>
          </div>
          <div className="text-center">
            <p className="text-muted-foreground">Success Rate</p>
            <p
              className={`font-semibold ${
                summaryStats.averageSuccessRate >= 90
                  ? 'text-green-600'
                  : summaryStats.averageSuccessRate >= 70
                  ? 'text-amber-600'
                  : 'text-red-600'
              }`}
            >
              {summaryStats.averageSuccessRate.toFixed(0)}%
            </p>
          </div>
          <div className="text-center">
            <p className="text-muted-foreground">Cost Variance</p>
            {summaryStats.costVariance == null ? (
              <p className="font-semibold text-muted-foreground" title="No run has recorded actual costs yet">
                —
              </p>
            ) : (
              <p
                className={`font-semibold flex items-center justify-center gap-1 ${
                  compareMoney(summaryStats.costVariance, ZERO) > 0
                    ? 'text-red-600'
                    : 'text-green-600'
                }`}
              >
                {compareMoney(summaryStats.costVariance, ZERO) > 0 ? (
                  <TrendingUp className="h-3 w-3" />
                ) : (
                  <TrendingDown className="h-3 w-3" />
                )}
                {compareMoney(summaryStats.costVariance, ZERO) > 0 ? '+' : ''}
                {formatPercent(summaryStats.costVariance, { undefinedLabel: '—' })}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Table */}
      {productRuns.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <p className="text-lg font-medium">No production runs found</p>
          <p className="text-sm mt-2">
            {modelIds.length === 0
              ? 'This product has no models assigned'
              : 'No production runs include this product yet'}
          </p>
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run #</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Success</TableHead>
                <TableHead className="text-right">Est. Cost</TableHead>
                <TableHead className="text-right">Actual Cost</TableHead>
                <TableHead className="text-right">Weight Variance</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {productRuns.map(({ run, itemQuantity, successRate, estimatedCost, actualCost }) => (
                <TableRow key={run.id}>
                  <TableCell className="font-mono font-medium">
                    <Link
                      to="/production-runs/$runId"
                      params={{ runId: run.id }}
                      className="hover:underline"
                    >
                      {run.run_number}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="text-sm">
                        {format(parseISO(run.started_at), 'MMM d, yyyy')}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {run.duration_hours ? formatDuration(run.duration_hours) : '—'}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusBadgeVariant(run.status)} className="gap-1">
                      {getStatusIcon(run.status)}
                      {formatStatus(run.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">{itemQuantity}</TableCell>
                  <TableCell className="text-right">
                    <span
                      className={
                        successRate >= 90
                          ? 'text-green-600'
                          : successRate >= 70
                          ? 'text-amber-600'
                          : 'text-red-600'
                      }
                    >
                      {successRate.toFixed(0)}%
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    {estimatedCost == null ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      formatCurrency(estimatedCost)
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {actualCost == null ? (
                      <span
                        className="text-muted-foreground"
                        title="No actual cost recorded for this run"
                      >
                        —
                      </span>
                    ) : (
                      formatCurrency(actualCost)
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {run.variance_percentage != null ? (
                      <span
                        className={
                          Math.abs(run.variance_percentage) > 10
                            ? 'text-red-600 font-medium'
                            : Math.abs(run.variance_percentage) > 5
                            ? 'text-amber-600'
                            : 'text-muted-foreground'
                        }
                      >
                        {run.variance_percentage > 0 ? '+' : ''}
                        {run.variance_percentage.toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" asChild>
                      <Link to="/production-runs/$runId" params={{ runId: run.id }}>
                        <ArrowUpRight className="h-4 w-4" />
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
