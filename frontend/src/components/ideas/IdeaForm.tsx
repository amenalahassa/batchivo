/**
 * Create or edit an idea's header: title, summary, status, source, tags, scores (spec 007).
 */
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type {
  IdeaCreate,
  IdeaDetail,
  IdeaScores,
  IdeaSource,
  WritableIdeaStatus,
} from '@/types/idea'

import {
  SCORE_LABELS,
  SCORE_NAMES,
  SOURCE_LABELS,
  STATUS_LABELS,
  WRITABLE_STATUSES,
} from './ideaText'

interface IdeaFormProps {
  initial?: IdeaDetail
  submitLabel?: string
  isSubmitting?: boolean
  error?: string | null
  onSubmit: (data: IdeaCreate) => void
  onCancel?: () => void
}

const EMPTY_SCORES: IdeaScores = {
  frequency: null,
  frustration: null,
  printability: null,
  gap: null,
  willingness_to_pay: null,
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

export function IdeaForm({
  initial,
  submitLabel = 'Save',
  isSubmitting,
  error,
  onSubmit,
  onCancel,
}: IdeaFormProps) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [summary, setSummary] = useState(initial?.summary ?? '')
  const [status, setStatus] = useState<WritableIdeaStatus>(
    initial && initial.status !== 'converted' ? initial.status : 'inbox'
  )
  const [source, setSource] = useState<IdeaSource>(initial?.source ?? 'manual')
  const [sourceUrl, setSourceUrl] = useState(initial?.source_url ?? '')
  const [tags, setTags] = useState((initial?.tags ?? []).join(', '))
  const [scores, setScores] = useState<IdeaScores>(initial?.scores ?? EMPTY_SCORES)
  const [problems, setProblems] = useState<string[]>([])

  const keepsConverted = initial?.status === 'converted'

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const found: string[] = []
    if (!title.trim()) found.push('Title is required')
    if (title.trim().length > 200) found.push('Title is at most 200 characters')
    if (sourceUrl.trim() && !isHttpUrl(sourceUrl.trim()))
      found.push('Link must start with http:// or https://')
    setProblems(found)
    if (found.length) return
    onSubmit({
      title: title.trim(),
      summary: summary.trim() || null,
      // A converted idea keeps its status unless the operator picks another.
      ...(keepsConverted && status === 'inbox' ? {} : { status }),
      source,
      source_url: sourceUrl.trim() || null,
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      scores,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" aria-label="Idea">
      <div className="space-y-1">
        <Label htmlFor="idea-title">Title</Label>
        <Input
          id="idea-title"
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Sun visor clip"
          autoFocus
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="idea-summary">Summary (markdown)</Label>
        <Textarea
          id="idea-summary"
          value={summary}
          rows={4}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="The problem and the idea in a few lines"
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="idea-status">Status</Label>
          <select
            id="idea-status"
            className="h-9 w-full rounded-md border bg-background px-2 text-sm"
            value={keepsConverted && status === 'inbox' ? '' : status}
            onChange={(e) => setStatus(e.target.value as WritableIdeaStatus)}
          >
            {keepsConverted && <option value="">Converted (keep)</option>}
            {WRITABLE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="idea-source">Source</Label>
          <select
            id="idea-source"
            className="h-9 w-full rounded-md border bg-background px-2 text-sm"
            value={source}
            onChange={(e) => setSource(e.target.value as IdeaSource)}
          >
            {(Object.keys(SOURCE_LABELS) as IdeaSource[]).map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="idea-source-url">Source link</Label>
        <Input
          id="idea-source-url"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
          placeholder="https://"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="idea-tags">Tags (comma separated)</Label>
        <Input
          id="idea-tags"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="car, clip"
        />
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Scores (1–5)</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {SCORE_NAMES.map((name) => (
            <label key={name} className="space-y-1 text-xs">
              <span>{SCORE_LABELS[name]}</span>
              <select
                aria-label={SCORE_LABELS[name]}
                className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                value={scores[name] ?? ''}
                onChange={(e) =>
                  setScores({
                    ...scores,
                    [name]: e.target.value ? Number(e.target.value) : null,
                  })
                }
              >
                <option value="">—</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      </fieldset>
      {(problems.length > 0 || error) && (
        <ul role="alert" className="space-y-1 text-sm text-destructive">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
          {error && <li>{error}</li>}
        </ul>
      )}
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={isSubmitting}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}
