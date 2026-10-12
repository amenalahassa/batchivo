/**
 * ChannelProfitabilityPanel — the period selector that makes the channel P&L
 * reachable.
 *
 * `ChannelReconciliation` renders a period that someone has to choose, and a
 * channel P&L is only meaningful over one: periodic costs are absorbed over a
 * period's actual order volume (FR-025), and a fee statement arrives per
 * period. This component owns that choice and nothing else.
 *
 * The default is the current month to date rather than a fixed window, because
 * that is the period whose statement has not arrived yet — the one where
 * planned-against-recorded still has an open remainder to look at.
 *
 * Dates are built from local calendar parts, not from an ISO slice of a UTC
 * instant: `new Date().toISOString()` west of UTC names yesterday for the first
 * hours of each day, which would silently drop or add an order at a period
 * boundary.
 */

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { ChannelReconciliation } from '@/components/pricing/ChannelReconciliation'
import { useChannelPnL } from '@/hooks/useFeeRules'

interface ChannelProfitabilityPanelProps {
  channelId: string
  currencySymbol?: string
}

/** A local calendar date as `YYYY-MM-DD`, with no timezone shift. */
function isoDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function currentMonthToDate(): { start: string; end: string } {
  const now = new Date()
  return {
    start: isoDate(new Date(now.getFullYear(), now.getMonth(), 1)),
    end: isoDate(now),
  }
}

export function ChannelProfitabilityPanel({
  channelId,
  currencySymbol = '£',
}: ChannelProfitabilityPanelProps) {
  const [period, setPeriod] = useState(currentMonthToDate)
  const inverted = period.start > period.end

  const { pnl, isLoading, error } = useChannelPnL({
    channelId,
    // An inverted range would ask the API for a period that cannot contain an
    // order; the operator is told instead of being shown an empty month.
    periodStart: inverted ? undefined : period.start,
    periodEnd: inverted ? undefined : period.end,
  })

  return (
    <Card data-testid="channel-profitability">
      <CardHeader>
        <CardTitle>Channel profitability</CardTitle>
        <CardDescription>
          What this channel charged over a period, against what the fee rules
          planned. Periodic costs are spread over the period&rsquo;s actual
          orders.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="pnl-period-start">Period start</Label>
            <Input
              id="pnl-period-start"
              type="date"
              value={period.start}
              onChange={(event) =>
                setPeriod((current) => ({ ...current, start: event.target.value }))
              }
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="pnl-period-end">Period end</Label>
            <Input
              id="pnl-period-end"
              type="date"
              value={period.end}
              onChange={(event) =>
                setPeriod((current) => ({ ...current, end: event.target.value }))
              }
            />
          </div>
          <Button variant="outline" onClick={() => setPeriod(currentMonthToDate())}>
            This month
          </Button>
        </div>

        {inverted ? (
          <p className="text-sm text-destructive" data-testid="pnl-period-inverted">
            The period ends before it starts, so there is nothing to report. Pick
            an end date on or after the start.
          </p>
        ) : isLoading ? (
          <div className="space-y-2" data-testid="pnl-loading">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : error ? (
          <p className="text-sm text-destructive" data-testid="pnl-error">
            This channel&rsquo;s profitability could not be loaded, so none of
            these figures are shown. {error.message}
          </p>
        ) : pnl ? (
          <ChannelReconciliation pnl={pnl} currencySymbol={currencySymbol} />
        ) : null}
      </CardContent>
    </Card>
  )
}
