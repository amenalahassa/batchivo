/**
 * A part's intended use, as Preflight's `intent.yaml` holds it (spec 009, US1).
 *
 * Values still "[À PRÉCISER]" and values only inferred (`déduit`) or
 * estimated (`estimée`) are highlighted, with the server's validation summary
 * (the same report as `pf.py validate`).
 */
import { Badge } from '@/components/ui/badge'
import type { Intent, IntentValidation } from '@/types/preflight'
import { isPlaceholder, valueText } from './preflightText'

const UNCONFIRMED = new Set(['déduit', 'estimée'])

function Field({ label, value }: { label: string; value: unknown }) {
  const unknown = isPlaceholder(value)
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={`whitespace-pre-wrap break-words text-sm ${unknown ? 'font-medium text-amber-700 dark:text-amber-300' : ''}`}
      >
        {valueText(value)}
      </dd>
    </div>
  )
}

function StatusBadge({ status }: { status: unknown }) {
  if (typeof status !== 'string') return null
  return (
    <Badge
      variant="outline"
      className={UNCONFIRMED.has(status) ? 'border-amber-500 text-amber-800 dark:text-amber-200' : ''}
    >
      {status}
    </Badge>
  )
}

function Items({ title, items }: { title: string; items: Record<string, unknown>[] | undefined }) {
  if (!items || items.length === 0) return null
  return (
    <section className="space-y-1">
      <h4 className="text-sm font-semibold">{title}</h4>
      <ul className="space-y-2">
        {items.map((item, index) => {
          const { status, ...rest } = item
          return (
            <li key={index} className="rounded-md border p-2">
              <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                #{index + 1} <StatusBadge status={status} />
              </div>
              <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {Object.entries(rest).map(([key, value]) => (
                  <Field key={key} label={key} value={value} />
                ))}
              </dl>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function IntentView({ intent, validation }: { intent: Intent; validation: IntentValidation }) {
  const { status: envStatus, ...environment } = intent.environment ?? {}
  return (
    <div className="space-y-4">
      {(validation.to_clarify.length > 0 ||
        validation.unconfirmed.length > 0 ||
        validation.missing.length > 0) && (
        <div role="status" className="rounded-md border border-amber-400 bg-amber-50 p-2 text-sm dark:bg-amber-950/40">
          {validation.to_clarify.length > 0 && (
            <p>
              <strong>{validation.to_clarify.length} to clarify:</strong> {validation.to_clarify.join(', ')}
            </p>
          )}
          {validation.unconfirmed.length > 0 && (
            <p>
              <strong>Not confirmed:</strong>{' '}
              {validation.unconfirmed.map((u) => `${u.field} (${u.status})`).join(', ')}
            </p>
          )}
          {validation.missing.length > 0 && (
            <p>
              <strong>Missing:</strong> {validation.missing.join(', ')}
            </p>
          )}
        </div>
      )}

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Function" value={intent.function} />
        <Field label="Category" value={intent.category} />
        <Field label="Quantity" value={intent.quantity} />
        <Field label="Selling" value={intent.selling} />
        <Field label="Sales channel" value={intent.sales_channel} />
        <Field label="Country" value={intent.country} />
      </dl>

      <Items title="Loads" items={intent.loads} />

      {intent.environment && (
        <section className="space-y-1">
          <h4 className="flex items-center gap-2 text-sm font-semibold">
            Environment <StatusBadge status={envStatus} />
          </h4>
          <dl className="grid grid-cols-1 gap-2 rounded-md border p-2 sm:grid-cols-3">
            {Object.entries(environment).map(([key, value]) => (
              <Field key={key} label={key} value={value} />
            ))}
          </dl>
        </section>
      )}

      <Items title="Interfaces" items={intent.interfaces} />

      {intent.success_criteria && intent.success_criteria.length > 0 && (
        <section className="space-y-1">
          <h4 className="text-sm font-semibold">Success criteria</h4>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {intent.success_criteria.map((criterion, index) => (
              <li key={index} className={isPlaceholder(criterion) ? 'text-amber-700 dark:text-amber-300' : ''}>
                {criterion}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
