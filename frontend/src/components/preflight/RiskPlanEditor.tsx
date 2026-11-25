/**
 * Edit a brief's risk part (class + risk.md) or its plan (plan.md) (spec 009, US1).
 *
 * Markdown is edited as text with a preview. The risk part is saved as a
 * whole (class and text together), as Preflight's `risk` step writes it; the
 * triage JSON written by the skill is kept unless the class or text changes.
 */
import { useState } from 'react'

import { Markdown } from '@/components/ideas/Markdown'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { RISK_CLASSES, type RiskClass, type RiskPart } from '@/types/preflight'
import { RISK_TEXT } from './preflightText'

interface MarkdownFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
}

function MarkdownField({ id, label, value, onChange }: MarkdownFieldProps) {
  const [preview, setPreview] = useState(false)
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>{label}</Label>
        <Button type="button" size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setPreview((p) => !p)}>
          {preview ? 'Edit' : 'Preview'}
        </Button>
      </div>
      {preview ? (
        <div className="min-h-28 rounded-md border p-2">
          <Markdown>{value || '_Nothing written yet._'}</Markdown>
        </div>
      ) : (
        <Textarea id={id} value={value} onChange={(e) => onChange(e.target.value)} className="min-h-40 font-mono text-xs" />
      )}
    </div>
  )
}

interface EditorBaseProps {
  saving: boolean
  error?: string | null
  onCancel: () => void
}

export function RiskEditor({
  riskClass,
  riskMd,
  triage,
  saving,
  error,
  onSave,
  onCancel,
}: EditorBaseProps & {
  riskClass: RiskClass | null
  riskMd: string | null
  triage: Record<string, unknown> | null
  onSave: (risk: RiskPart) => void
}) {
  const [klass, setKlass] = useState<RiskClass | ''>(riskClass ?? '')
  const [text, setText] = useState(riskMd ?? '')
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSave({ risk_class: klass || null, risk_md: text || null, triage })
      }}
    >
      <div className="space-y-1">
        <Label htmlFor="risk-class">Risk class</Label>
        <select
          id="risk-class"
          className="h-9 w-full rounded-md border bg-background px-2 text-sm sm:w-60"
          value={klass}
          onChange={(e) => setKlass(e.target.value as RiskClass | '')}
        >
          <option value="">Not assessed</option>
          {RISK_CLASSES.map((c) => (
            <option key={c} value={c}>
              {RISK_TEXT[c]}
            </option>
          ))}
        </select>
      </div>
      <MarkdownField id="risk-md" label="risk.md" value={text} onChange={setText} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save risk'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

export function PlanEditor({
  planMd,
  saving,
  error,
  onSave,
  onCancel,
}: EditorBaseProps & { planMd: string | null; onSave: (planMd: string | null) => void }) {
  const [text, setText] = useState(planMd ?? '')
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(text || null)
      }}
    >
      <MarkdownField id="plan-md" label="plan.md" value={text} onChange={setText} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save plan'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
