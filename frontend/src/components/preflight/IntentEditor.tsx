/**
 * Edit a part's intent (spec 009, US1, clarification Q4).
 *
 * The simple fields are a form; loads, environment and interfaces (nested,
 * each with its value status) are YAML or JSON text. The whole intent is sent
 * as `intent_yaml` and the server -- the one YAML parser and the one validator
 * -- reads and checks it; its error names the field. Keys the form does not
 * show (slug, images, a skill's own extras) are kept as they were.
 */
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { PLACEHOLDER, SALES_CHANNELS, type Intent } from '@/types/preflight'
import { blockText } from './preflightText'
import { composeIntentYaml } from './preflightLogic'

const CATEGORIES = [
  'support',
  'crochet',
  'clip',
  'boîtier',
  'adaptateur',
  'pièce de rechange',
  'décoratif',
  'jouet',
  'autre',
]

interface IntentEditorProps {
  intent: Intent | null
  saving: boolean
  error?: string | null
  onSave: (intentYaml: string) => void
  onCancel: () => void
}

function textOf(value: unknown): string {
  if (value === undefined || value === null) return ''
  return blockText(value).trimEnd()
}

export function IntentEditor({ intent, saving, error, onSave, onCancel }: IntentEditorProps) {
  const [form, setForm] = useState({
    function: (intent?.function as string | undefined) ?? '',
    category: (intent?.category as string | undefined) ?? '',
    quantity: intent?.quantity !== undefined ? String(intent.quantity) : '1',
    selling: Boolean(intent?.selling),
    sales_channel: (intent?.sales_channel as string | undefined) ?? 'none',
    country: (intent?.country as string | undefined) ?? '',
    success_criteria: (intent?.success_criteria ?? []).join('\n'),
    loads: textOf(intent?.loads),
    environment: textOf(intent?.environment),
    interfaces: textOf(intent?.interfaces),
  })
  const set = (key: keyof typeof form) => (value: string | boolean) =>
    setForm((current) => ({ ...current, [key]: value }))

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(composeIntentYaml(intent, form))
      }}
    >
      <p className="text-xs text-muted-foreground">
        Leave a field empty, or write {PLACEHOLDER}, when it is not known yet. Nothing is invented.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="intent-function">Function</Label>
          <Input
            id="intent-function"
            value={form.function}
            placeholder="What the part does, in one sentence"
            onChange={(e) => set('function')(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="intent-category">Category</Label>
          <Input
            id="intent-category"
            list="intent-categories"
            value={form.category}
            onChange={(e) => set('category')(e.target.value)}
          />
          <datalist id="intent-categories">
            {CATEGORIES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>
        <div className="space-y-1">
          <Label htmlFor="intent-quantity">Quantity</Label>
          <Input
            id="intent-quantity"
            inputMode="numeric"
            value={form.quantity}
            onChange={(e) => set('quantity')(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="intent-channel">Sales channel</Label>
          <select
            id="intent-channel"
            className="h-9 w-full rounded-md border bg-background px-2 text-sm"
            value={form.sales_channel}
            onChange={(e) => set('sales_channel')(e.target.value)}
          >
            {[...SALES_CHANNELS, ...(SALES_CHANNELS.includes(form.sales_channel as never) ? [] : [form.sales_channel])].map(
              (channel) => (
                <option key={channel} value={channel}>
                  {channel}
                </option>
              )
            )}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="intent-country">Country</Label>
          <Input id="intent-country" value={form.country} onChange={(e) => set('country')(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.selling} onChange={(e) => set('selling')(e.target.checked)} />
          Sold to customers
        </label>
      </div>

      <div className="space-y-1">
        <Label htmlFor="intent-criteria">Success criteria (one per line)</Label>
        <Textarea
          id="intent-criteria"
          value={form.success_criteria}
          onChange={(e) => set('success_criteria')(e.target.value)}
          className="min-h-16"
        />
      </div>

      {(['loads', 'environment', 'interfaces'] as const).map((key) => (
        <div key={key} className="space-y-1">
          <Label htmlFor={`intent-${key}`} className="capitalize">
            {key} (YAML or JSON)
          </Label>
          <Textarea
            id={`intent-${key}`}
            value={form[key]}
            spellCheck={false}
            onChange={(e) => set(key)(e.target.value)}
            className="min-h-28 font-mono text-xs"
          />
        </div>
      ))}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save intent'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
