/**
 * ExchangeRatePanel — the sales still waiting on an exchange rate, and the
 * form that gives them one (T223, FR-028h).
 *
 * A sale in a currency other than the books' freezes the rate in force on the
 * day. Where none had ever been fetched the snapshot recorded "no exchange
 * rate was available" and the line's margin cannot be stated: a cost in one
 * currency cannot be taken from a price in another at an assumed parity. The
 * edge case says the operator is asked for the rate; this is where.
 *
 * - **The waiting list** is every role's to read, grouped by currency pair,
 *   since one rate answers every line on that pair sold on its date.
 * - **The form** is an admin's: a rate moves every margin built on it. It
 *   fills only lines that froze none and never revises a frozen rate
 *   (FR-028j); a second, different rate for the same pair and day is refused
 *   with the reason the API gives.
 *
 * The rate is sent as the decimal string it was typed as, never a number.
 */

import { useMemo, useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useFxWaitingLines, useRecordManualFxRate } from '@/hooks/useFxRates'
import { apiErrorDetail } from '@/lib/apiError'
import type { FxWaitingLine } from '@/types/pricing'

const CURRENCY = /^[A-Za-z]{3}$/
const RATE = /^\d+(\.\d+)?$/
const ZERO = /^0+(\.0+)?$/

interface ExchangeRatePanelProps {
  /** False for a member or viewer: recording a rate needs an admin or owner. */
  canEdit?: boolean
}

function pairOf(line: FxWaitingLine): string {
  return `${line.base_currency}/${line.quote_currency}`
}

export function ExchangeRatePanel({ canEdit = true }: ExchangeRatePanelProps) {
  const waiting = useFxWaitingLines()
  const record = useRecordManualFxRate()
  const [base, setBase] = useState('')
  const [quote, setQuote] = useState('')
  const [rate, setRate] = useState('')
  const [rateDate, setRateDate] = useState('')
  const [invalid, setInvalid] = useState<string | null>(null)

  const byPair = useMemo(() => {
    const groups = new Map<string, FxWaitingLine[]>()
    for (const line of waiting.data?.lines ?? []) {
      groups.set(pairOf(line), [...(groups.get(pairOf(line)) ?? []), line])
    }
    return [...groups.entries()]
  }, [waiting.data])

  const choose = (line: FxWaitingLine) => {
    setBase(line.base_currency)
    setQuote(line.quote_currency)
    if (line.sold_on) setRateDate(line.sold_on)
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setInvalid(null)
    const typed = rate.trim()
    if (!CURRENCY.test(base) || !CURRENCY.test(quote)) {
      return setInvalid('Give both currencies as three-letter codes, e.g. USD and GBP')
    }
    if (base.toUpperCase() === quote.toUpperCase()) {
      return setInvalid('A currency converts to itself at parity; no rate is needed')
    }
    if (!RATE.test(typed) || ZERO.test(typed)) {
      return setInvalid('Enter the rate as a positive decimal, e.g. 0.7850')
    }
    record.mutate({
      base_currency: base.toUpperCase(),
      quote_currency: quote.toUpperCase(),
      rate: typed,
      ...(rateDate ? { rate_date: rateDate } : {}),
    })
  }

  return (
    <Card data-testid="exchange-rate-panel">
      <CardHeader>
        <CardTitle>Exchange rates</CardTitle>
        <CardDescription>
          Sales in another currency freeze the day&rsquo;s rate. Where none was available, the
          line&rsquo;s margin waits on one; a rate entered here fills those lines and never
          changes a rate already frozen.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {waiting.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : byPair.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="fx-nothing-waiting">
            No sale is waiting on an exchange rate.
          </p>
        ) : (
          <ul className="space-y-3" data-testid="fx-waiting-list">
            {byPair.map(([pair, lines]) => (
              <li key={pair} className="rounded-md border p-3" data-testid={`fx-waiting-${pair}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {pair} <Badge variant="secondary">{lines.length} waiting</Badge>
                  </span>
                  {canEdit && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => choose(lines[0])}
                    >
                      Enter this rate
                    </Button>
                  )}
                </div>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                  {lines.map((line) => (
                    <li key={line.order_item_id}>
                      {line.order_number} · {line.product_name}
                      {line.sold_on ? ` · sold ${line.sold_on}` : ''}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}

        <form
          onSubmit={submit}
          className="space-y-3 rounded-md border p-4"
          aria-label="Enter an exchange rate"
        >
          <fieldset
            disabled={!canEdit}
            className="m-0 grid min-w-0 gap-3 border-0 p-0 sm:grid-cols-4"
          >
            <div className="space-y-1">
              <Label htmlFor="fx-base">From</Label>
              <Input
                id="fx-base"
                placeholder="USD"
                maxLength={3}
                value={base}
                onChange={(event) => setBase(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fx-quote">To</Label>
              <Input
                id="fx-quote"
                placeholder="GBP"
                maxLength={3}
                value={quote}
                onChange={(event) => setQuote(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fx-rate">Rate</Label>
              <Input
                id="fx-rate"
                inputMode="decimal"
                placeholder="0.7850"
                value={rate}
                onChange={(event) => setRate(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fx-date">For the day</Label>
              <Input
                id="fx-date"
                type="date"
                value={rateDate}
                onChange={(event) => setRateDate(event.target.value)}
              />
            </div>
          </fieldset>
          <p className="text-xs text-muted-foreground">
            One unit of the first currency is the rate in the second. Recorded as entered by you,
            never as fetched.
          </p>

          {invalid && (
            <p className="text-sm text-destructive" data-testid="fx-invalid">
              {invalid}
            </p>
          )}
          {record.error && (
            <Alert variant="destructive" data-testid="fx-refused">
              <AlertTitle>Not recorded</AlertTitle>
              <AlertDescription>{apiErrorDetail(record.error)}</AlertDescription>
            </Alert>
          )}
          {record.isSuccess && record.data && (
            <p className="text-sm text-muted-foreground" data-testid="fx-recorded">
              Recorded {record.data.base_currency}/{record.data.quote_currency} at{' '}
              {record.data.rate} for {record.data.rate_date}, as entered;{' '}
              {record.data.lines_filled} waiting line
              {record.data.lines_filled === 1 ? '' : 's'} filled.
            </p>
          )}

          {canEdit ? (
            <Button type="submit" disabled={record.isPending}>
              {record.isPending ? 'Recording…' : 'Record rate'}
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="fx-read-only">
              Entering a rate needs an admin or owner.
            </p>
          )}
        </form>
      </CardContent>
    </Card>
  )
}
