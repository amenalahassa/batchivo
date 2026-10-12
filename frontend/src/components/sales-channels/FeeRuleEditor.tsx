/**
 * FeeRuleEditor — the real fee stack a channel charges (task T081).
 *
 * The thing this editor is designed around is that a fee's **basis** is the
 * decision that matters most and is the one easiest to get wrong. A fee of
 * 6.5% charged on the item alone and the same 6.5% charged on the item plus
 * shipping are different amounts on every order that ships, and the second is
 * what marketplaces actually charge. So the basis is a first-class field with
 * its consequence spelled out beside each option, not a dropdown of jargon.
 *
 * Two affordances that exist because of how fee rules go wrong in practice:
 *
 * * **A rate is disabled on a count basis.** A percentage of a quantity is not
 *   an amount, and the backend refuses it (`422`). Disabling the field means
 *   the operator never types a figure that will be rejected.
 * * **Closing a rule is offered beside deleting it.** A rule the channel has
 *   stopped charging should be closed with an end date, not deleted: closing
 *   keeps a past order's fees explainable, deleting makes them unreproducible.
 *
 * Writing needs admin or owner (FR-007a). This component does not police that
 * — the API does — but it accepts `canEdit` so a member sees the stack read-only
 * rather than a form that will 403 on submit.
 */

import { useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import { formatMoney, formatPercent } from '@/lib/money'
import {
  useCreateFeeRule,
  useDeleteFeeRule,
  useFeeRules,
  useUpdateFeeRule,
} from '@/hooks/useFeeRules'
import {
  BASES_IN_ORDER,
  BASIS_CONSEQUENCE,
  BASIS_LABEL,
  COUNT_BASES,
} from '@/lib/pricing/feeBases'
import type { FeeBasis, FeeRule, FeeRuleCreate } from '@/types/pricing'

interface FeeRuleEditorProps {
  channelId: string
  /** False for a member or viewer: the stack is shown read-only (FR-007a). */
  canEdit?: boolean
  currencySymbol?: string
}

interface DraftRule {
  name: string
  basis: FeeBasis
  rate_pct: string
  fixed_amount: string
  min_amount: string
  max_amount: string
  incidence_pct: string
  sort_order: string
  applies_from: string
}

function emptyDraft(nextSortOrder: number): DraftRule {
  return {
    name: '',
    basis: 'item_plus_shipping',
    rate_pct: '',
    fixed_amount: '',
    min_amount: '',
    max_amount: '',
    incidence_pct: '',
    sort_order: String(nextSortOrder),
    applies_from: new Date().toISOString().slice(0, 10),
  }
}

/** Turn the draft into the create payload, dropping the fields left blank. */
function toPayload(draft: DraftRule): FeeRuleCreate {
  const payload: FeeRuleCreate = {
    name: draft.name.trim(),
    basis: draft.basis,
    applies_from: draft.applies_from,
    sort_order: Number.parseInt(draft.sort_order || '0', 10),
  }
  // A count basis carries its charge in the fixed amount; sending a rate would
  // be refused, so it is not sent at all.
  if (!COUNT_BASES.has(draft.basis) && draft.rate_pct !== '') {
    payload.rate_pct = draft.rate_pct
  }
  if (draft.fixed_amount !== '') payload.fixed_amount = draft.fixed_amount
  if (draft.min_amount !== '') payload.min_amount = draft.min_amount
  if (draft.max_amount !== '') payload.max_amount = draft.max_amount
  if (draft.incidence_pct !== '') payload.incidence_pct = draft.incidence_pct
  return payload
}

function RuleRow({
  rule,
  channelId,
  canEdit,
  symbol,
}: {
  rule: FeeRule
  channelId: string
  canEdit: boolean
  symbol: string
}) {
  const update = useUpdateFeeRule(channelId)
  const remove = useDeleteFeeRule(channelId)
  const isCount = COUNT_BASES.has(rule.basis)
  const closed = rule.applies_to !== null

  return (
    <TableRow data-testid={`fee-rule-${rule.name}`}>
      <TableCell>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{rule.name}</span>
          {rule.incidence_pct !== null ? (
            <Badge variant="warning">
              {formatPercent(rule.incidence_pct, { places: 0 })} of orders
            </Badge>
          ) : null}
          {closed ? <Badge variant="secondary">Closed {rule.applies_to}</Badge> : null}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          from {rule.applies_from}
          {rule.max_amount !== null ? ` · capped at ${formatMoney(rule.max_amount, symbol)}` : ''}
          {rule.min_amount !== null
            ? ` · at least ${formatMoney(rule.min_amount, symbol)}`
            : ''}
        </p>
      </TableCell>
      <TableCell>
        <span>{BASIS_LABEL[rule.basis] ?? rule.basis}</span>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {BASIS_CONSEQUENCE[rule.basis]}
        </p>
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {isCount ? '—' : formatPercent(rule.rate_pct, { places: 2 })}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {formatMoney(rule.fixed_amount, symbol)}
      </TableCell>
      <TableCell className="text-right">
        {canEdit ? (
          <div className="flex justify-end gap-1">
            {!closed ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate({
                    ruleId: rule.id,
                    data: { applies_to: new Date().toISOString().slice(0, 10) },
                  })
                }
                data-testid={`fee-rule-close-${rule.name}`}
                title="Stop charging this fee from today, keeping past orders explainable"
              >
                Close
              </Button>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate(rule.id)}
              data-testid={`fee-rule-delete-${rule.name}`}
              title="Delete a rule entered by mistake; prefer Close for one you stopped paying"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ) : null}
      </TableCell>
    </TableRow>
  )
}

export function FeeRuleEditor({
  channelId,
  canEdit = true,
  currencySymbol = '£',
}: FeeRuleEditorProps) {
  const { rules, isLoading, error } = useFeeRules(channelId)
  const create = useCreateFeeRule(channelId)
  const nextSortOrder = rules.length === 0 ? 10 : Math.max(...rules.map((r) => r.sort_order)) + 10
  const [draft, setDraft] = useState<DraftRule>(() => emptyDraft(nextSortOrder))
  const [adding, setAdding] = useState(false)

  const rateDisabled = COUNT_BASES.has(draft.basis)

  const set = <K extends keyof DraftRule>(key: K, value: DraftRule[K]) =>
    setDraft((current) => ({ ...current, [key]: value }))

  const submit = () => {
    create.mutate(toPayload(draft), {
      onSuccess: () => {
        setDraft(emptyDraft(nextSortOrder + 10))
        setAdding(false)
      },
    })
  }

  return (
    <Card data-testid="fee-rule-editor">
      <CardHeader>
        <CardTitle>Fee rules</CardTitle>
        <CardDescription>
          What this channel actually charges. One blended percentage cannot express a
          transaction fee, a payment fee and a listing fee at once, and the margin is
          wrong by whichever ones are missing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading fee rules…</p>
        ) : null}

        {error ? (
          <p className="text-sm text-destructive" data-testid="fee-rule-error">
            Could not load the fee rules. The margin shown elsewhere may be missing fees.
          </p>
        ) : null}

        {!isLoading && rules.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="fee-rule-empty">
            No fee rules yet. Until one is added this channel is costed as charging
            nothing, which is almost certainly not what the marketplace does.
          </p>
        ) : null}

        {rules.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fee</TableHead>
                <TableHead>Charged on</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                <TableHead className="text-right">Fixed</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.map((rule) => (
                <RuleRow
                  key={rule.id}
                  rule={rule}
                  channelId={channelId}
                  canEdit={canEdit}
                  symbol={currencySymbol}
                />
              ))}
            </TableBody>
          </Table>
        ) : null}

        {canEdit && !adding ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setAdding(true)}
            data-testid="fee-rule-add"
          >
            <Plus className="mr-2 h-4 w-4" />
            Add a fee
          </Button>
        ) : null}

        {canEdit && adding ? (
          <div className="space-y-4 rounded-lg border p-4" data-testid="fee-rule-draft">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="fee-rule-name">Name</Label>
                <Input
                  id="fee-rule-name"
                  value={draft.name}
                  placeholder="e.g. transaction"
                  onChange={(event) => set('name', event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Use the name on the statement, so a recorded actual can be matched to it.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-basis">Charged on</Label>
                <Select
                  value={draft.basis}
                  onValueChange={(value) => set('basis', value as FeeBasis)}
                >
                  <SelectTrigger id="fee-rule-basis">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BASES_IN_ORDER.map((basis) => (
                      <SelectItem key={basis} value={basis}>
                        {BASIS_LABEL[basis]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {BASIS_CONSEQUENCE[draft.basis]}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-rate">Rate (%)</Label>
                <Input
                  id="fee-rule-rate"
                  type="number"
                  step="0.0001"
                  min="0"
                  max="100"
                  value={draft.rate_pct}
                  disabled={rateDisabled}
                  onChange={(event) => set('rate_pct', event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  {rateDisabled
                    ? 'a percentage of a count is not an amount — put the charge in Fixed'
                    : 'the percentage charged on the basis above'}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-fixed">Fixed amount</Label>
                <Input
                  id="fee-rule-fixed"
                  type="number"
                  step="0.01"
                  min="0"
                  value={draft.fixed_amount}
                  onChange={(event) => set('fixed_amount', event.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-min">Minimum (optional)</Label>
                <Input
                  id="fee-rule-min"
                  type="number"
                  step="0.01"
                  min="0"
                  value={draft.min_amount}
                  onChange={(event) => set('min_amount', event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  for a &ldquo;percentage, but at least this much&rdquo; processing fee
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-max">Maximum (optional)</Label>
                <Input
                  id="fee-rule-max"
                  type="number"
                  step="0.01"
                  min="0"
                  value={draft.max_amount}
                  onChange={(event) => set('max_amount', event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  for a capped fee; it will stop rising with the price
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-incidence">Share of orders (optional)</Label>
                <Input
                  id="fee-rule-incidence"
                  type="number"
                  step="0.01"
                  min="0"
                  max="100"
                  value={draft.incidence_pct}
                  onChange={(event) => set('incidence_pct', event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  for a fee that lands on only some orders. The figure is labelled an
                  expectation wherever it appears.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="fee-rule-from">Charged from</Label>
                <Input
                  id="fee-rule-from"
                  type="date"
                  value={draft.applies_from}
                  onChange={(event) => set('applies_from', event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  back-date this to when the marketplace started charging it, so past
                  orders keep the right fees
                </p>
              </div>
            </div>

            {create.error ? (
              <p className="text-sm text-destructive" data-testid="fee-rule-save-error">
                {create.error.message}
              </p>
            ) : null}

            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={submit}
                disabled={create.isPending || draft.name.trim() === ''}
                data-testid="fee-rule-save"
              >
                {create.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Save fee
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setAdding(false)}
                disabled={create.isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
