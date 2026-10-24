/**
 * FeeActualForm — record what a channel's statement actually charged (T224).
 *
 * `POST /reconciliation/fee-actuals` existed, wrapped by `useRecordFeeActual`,
 * and nothing on screen called it: the reconciliation view read plan against
 * actuals and offered no way to enter one. Two scopes, as the API has:
 *
 * - **A period total per fee category** (FR-041a) — the routine path, typed
 *   from a monthly statement.
 * - **One order's figure** (FR-041b) — an override for an order the statement
 *   itemised, optionally naming the statement period it appeared in so it is
 *   counted in that period and no other.
 *
 * What it records is labelled as entered (FR-041e): a figure typed by a person
 * is never presented as observed. Where an order amount would take the
 * period's unallocated remainder below zero the API answers 409, and the form
 * shows that reason rather than a status code.
 *
 * The amount is sent as the decimal string it was typed as, never a number.
 */

import { useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRecordFeeActual } from '@/hooks/useFeeRules'
import { apiErrorDetail, apiErrorStatus } from '@/lib/apiError'
import type { FeeActualCreate } from '@/types/pricing'

type Scope = 'period' | 'order'

const AMOUNT = /^-?\d+(\.\d{1,2})?$/

interface FeeActualFormProps {
  channelId: string
  /** The period the panel is showing, used as the period-scope default. */
  periodStart: string
  periodEnd: string
  currencySymbol?: string
  /** False for a member or viewer: the API needs an admin to record a fee. */
  canEdit?: boolean
}

export function FeeActualForm({
  channelId,
  periodStart,
  periodEnd,
  currencySymbol = '£',
  canEdit = true,
}: FeeActualFormProps) {
  const record = useRecordFeeActual()
  const [scope, setScope] = useState<Scope>('period')
  const [category, setCategory] = useState('')
  const [amount, setAmount] = useState('')
  const [orderId, setOrderId] = useState('')
  const [statementStart, setStatementStart] = useState('')
  const [statementEnd, setStatementEnd] = useState('')
  const [invalid, setInvalid] = useState<string | null>(null)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setInvalid(null)
    const typed = amount.trim()
    if (!category.trim()) return setInvalid('Name the fee category the statement charged')
    if (!AMOUNT.test(typed)) return setInvalid('Enter the amount as it appears, e.g. 12.40')
    if (scope === 'order' && !orderId.trim()) return setInvalid('Name the order this fee was for')
    if (scope === 'order' && Boolean(statementStart) !== Boolean(statementEnd)) {
      return setInvalid('Give both ends of the statement period, or neither')
    }

    const body: FeeActualCreate = {
      sales_channel_id: channelId,
      fee_category: category.trim(),
      amount: typed,
    }
    if (scope === 'period') {
      body.period_start = periodStart
      body.period_end = periodEnd
    } else {
      body.order_id = orderId.trim()
      if (statementStart && statementEnd) {
        body.statement_period_start = statementStart
        body.statement_period_end = statementEnd
      }
    }
    record.mutate(body, {
      onSuccess: () => {
        setAmount('')
        setOrderId('')
      },
    })
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border p-4"
      data-testid="fee-actual-form"
      aria-label="Record a fee from a statement"
    >
      <div>
        <p className="font-medium">Record a fee from a statement</p>
        <p className="text-sm text-muted-foreground">
          Recorded as entered by you, never as observed. A period total is the usual path;
          an order figure overrides one order the statement itemised.
        </p>
      </div>

      <fieldset className="flex gap-4" disabled={!canEdit}>
        <legend className="sr-only">Scope</legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="fee-actual-scope"
            checked={scope === 'period'}
            onChange={() => setScope('period')}
          />
          Period total ({periodStart} to {periodEnd})
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="radio"
            name="fee-actual-scope"
            checked={scope === 'order'}
            onChange={() => setScope('order')}
          />
          One order
        </label>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="fee-actual-category">Fee category</Label>
          <Input
            id="fee-actual-category"
            placeholder="transaction"
            value={category}
            disabled={!canEdit}
            onChange={(event) => setCategory(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="fee-actual-amount">Amount ({currencySymbol})</Label>
          <Input
            id="fee-actual-amount"
            inputMode="decimal"
            placeholder="12.40"
            value={amount}
            disabled={!canEdit}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>
        {scope === 'order' && (
          <>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="fee-actual-order">Order ID</Label>
              <Input
                id="fee-actual-order"
                value={orderId}
                disabled={!canEdit}
                onChange={(event) => setOrderId(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fee-actual-statement-start">Statement period start</Label>
              <Input
                id="fee-actual-statement-start"
                type="date"
                value={statementStart}
                disabled={!canEdit}
                onChange={(event) => setStatementStart(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fee-actual-statement-end">Statement period end</Label>
              <Input
                id="fee-actual-statement-end"
                type="date"
                value={statementEnd}
                disabled={!canEdit}
                onChange={(event) => setStatementEnd(event.target.value)}
              />
            </div>
          </>
        )}
      </div>

      {invalid && (
        <p className="text-sm text-destructive" data-testid="fee-actual-invalid">
          {invalid}
        </p>
      )}
      {record.error && (
        <Alert variant="destructive" data-testid="fee-actual-refused">
          <AlertTitle>
            {apiErrorStatus(record.error) === 409 ? 'Not recorded: it conflicts' : 'Not recorded'}
          </AlertTitle>
          <AlertDescription>{apiErrorDetail(record.error)}</AlertDescription>
        </Alert>
      )}
      {record.isSuccess && record.data && (
        <p className="text-sm text-muted-foreground" data-testid="fee-actual-recorded">
          Recorded {currencySymbol}
          {record.data.amount} of {record.data.fee_category}, as entered.
        </p>
      )}

      {canEdit ? (
        <Button type="submit" disabled={record.isPending}>
          {record.isPending ? 'Recording…' : 'Record fee'}
        </Button>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="fee-actual-read-only">
          Recording a fee needs an admin or owner.
        </p>
      )}
    </form>
  )
}
