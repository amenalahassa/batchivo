/**
 * FeeBreakdownTable — every fee, what it was charged on, and whether it bound.
 *
 * Three things this table exists to make visible, each of which is a way an
 * operator currently mistrusts a fee figure:
 *
 * 1. **The basis.** A fee of CA$4.22 is 6.5% of the item plus shipping, or 3%
 *    of the order total, or a flat charge — and which it is decides whether it
 *    moves when the price does. The basis is a column, not a tooltip (FR-021).
 * 2. **Whether a clamp bound.** A capped fee charges less than its rate
 *    implies, and without saying so it reads as a miscalculated one (FR-021c).
 *    That has to be visible at a glance, not derived by the reader.
 * 3. **Whether it is an expectation.** A fee applied at an expected incidence
 *    is what the channel charges on average, not what it charged here
 *    (FR-029). Presenting the two identically is how a planning figure becomes
 *    mistaken for a receipt.
 *
 * Periodic rules are shown in their own section rather than dropped: a listing
 * fee the operator configured and never sees again is a cost they stop
 * believing in. They are labelled as absorbed over a period (FR-025), because
 * charging them on one sale would double-count them.
 *
 * Money is rendered from the decimal string the API sent — no Number(), no
 * toFixed on a parsed float (Constitution IV).
 */

import { Fragment } from 'react'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { formatMoney, formatPercent } from '@/lib/money'
import { BASIS_LABEL, COUNT_BASES } from '@/lib/pricing/feeBases'
import type { FeeCharge } from '@/types/pricing'

interface FeeBreakdownTableProps {
  charges: FeeCharge[]
  /** Periodic rules absorbed over a period rather than charged here (FR-025). */
  periodic?: FeeCharge[]
  /** The total as the API computed it, rounded once. Shown in the footer. */
  total?: string | null
  currencySymbol?: string
  className?: string
}

/** The rate and fixed amount behind one charge, in one readable phrase. */
function rateDescription(charge: FeeCharge, symbol: string): string {
  const parts: string[] = []
  if (!COUNT_BASES.has(charge.basis) && charge.rate_pct && charge.rate_pct !== '0') {
    parts.push(formatPercent(charge.rate_pct, { places: 2 }))
  }
  if (charge.fixed_amount && charge.fixed_amount !== '0' && charge.fixed_amount !== '0.00') {
    parts.push(`+ ${formatMoney(charge.fixed_amount, symbol)}`)
  }
  return parts.length > 0 ? parts.join(' ') : '—'
}

function ChargeRow({
  charge,
  symbol,
  periodic = false,
}: {
  charge: FeeCharge
  symbol: string
  periodic?: boolean
}) {
  const clamped = charge.clamp_applied !== null && charge.clamp_applied !== undefined

  return (
    <TableRow data-testid={`fee-row-${charge.name}`}>
      <TableCell className="align-top">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{charge.name}</span>
          {charge.is_expected ? (
            <Badge variant="warning" data-testid={`fee-expected-${charge.name}`}>
              Expected
            </Badge>
          ) : null}
          {clamped ? (
            <Badge
              variant="outline"
              data-testid={`fee-clamp-${charge.name}`}
              data-clamp={charge.clamp_applied}
            >
              {charge.clamp_applied === 'max' ? 'Cap applied' : 'Minimum applied'}
            </Badge>
          ) : null}
          {periodic ? <Badge variant="secondary">Absorbed per period</Badge> : null}
        </div>
        {charge.is_expected ? (
          <p
            className="mt-0.5 text-xs text-muted-foreground"
            data-testid={`fee-expected-note-${charge.name}`}
          >
            charged on {formatPercent(charge.incidence_pct, { places: 0 })} of orders — an
            expectation, not an amount charged here
          </p>
        ) : null}
        {clamped ? (
          <p
            className="mt-0.5 text-xs text-muted-foreground"
            data-testid={`fee-clamp-note-${charge.name}`}
          >
            {charge.clamp_applied === 'max'
              ? 'the cap bound, so this fee stops rising with the price'
              : 'the minimum bound, so this fee stops falling with the price'}
          </p>
        ) : null}
      </TableCell>

      <TableCell className="align-top" data-testid={`fee-basis-${charge.name}`}>
        <span>{BASIS_LABEL[charge.basis] ?? charge.basis}</span>
        <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
          {COUNT_BASES.has(charge.basis)
            ? `× ${charge.basis_amount}`
            : formatMoney(charge.basis_amount, symbol)}
        </p>
      </TableCell>

      <TableCell className="align-top text-right tabular-nums text-muted-foreground">
        {rateDescription(charge, symbol)}
      </TableCell>

      <TableCell
        className={cn('align-top text-right font-medium tabular-nums')}
        data-testid={`fee-amount-${charge.name}`}
      >
        {formatMoney(charge.amount, symbol)}
      </TableCell>
    </TableRow>
  )
}

export function FeeBreakdownTable({
  charges,
  periodic = [],
  total,
  currencySymbol = '$',
  className,
}: FeeBreakdownTableProps) {
  const nothingCharged = charges.length === 0 && periodic.length === 0

  if (nothingCharged) {
    return (
      <p className={cn('text-sm text-muted-foreground', className)} data-testid="fee-table-empty">
        This channel has no fee rules configured, so no fee is charged. That is a
        configuration, not a discount — if the marketplace charges you something,
        it is not modelled yet.
      </p>
    )
  }

  return (
    <div className={className} data-testid="fee-breakdown-table">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Fee</TableHead>
            <TableHead>Charged on</TableHead>
            <TableHead className="text-right">Rate</TableHead>
            <TableHead className="text-right">Amount</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {charges.map((charge) => (
            <Fragment key={`${charge.name}-${charge.basis}`}>
              <ChargeRow charge={charge} symbol={currencySymbol} />
            </Fragment>
          ))}
        </TableBody>
        {total !== null && total !== undefined && charges.length > 0 ? (
          <TableFooter>
            <TableRow>
              <TableCell colSpan={3}>Total fees</TableCell>
              <TableCell className="text-right tabular-nums" data-testid="fee-total">
                {formatMoney(total, currencySymbol)}
              </TableCell>
            </TableRow>
          </TableFooter>
        ) : null}
      </Table>

      {periodic.length > 0 ? (
        <div className="mt-4" data-testid="fee-periodic-section">
          <h4 className="text-sm font-medium">Not charged on this sale</h4>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Listing and subscription fees are absorbed over a period&rsquo;s actual order
            volume, so they are not charged against one unit. See the channel
            profitability view for what they cost per order.
          </p>
          <Table className="mt-2">
            <TableHeader>
              <TableRow>
                <TableHead>Fee</TableHead>
                <TableHead>Charged on</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                <TableHead className="text-right">Amount</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {periodic.map((charge) => (
                <ChargeRow
                  key={`${charge.name}-periodic`}
                  charge={charge}
                  symbol={currencySymbol}
                  periodic
                />
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  )
}
