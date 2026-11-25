/**
 * The notes of a file, listed beside the viewer (spec 004, T052; FR-028; spec 009 US2).
 *
 * Readable and usable without the 3D view, at phone width: number, text,
 * status, author and date, a status filter and an archived toggle. An earlier
 * version's open note (a ghost) can be resolved here or carried forward.
 *
 * Spec 009: a note raised by Preflight (or a printer, or the slicer) shows its
 * severity, rule and measured-versus-expected value; notes filter by source and
 * severity; an open note can be dismissed with a written reason, and reopened.
 */
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { FileNote, NoteSeverity, NoteSource, NoteStatus } from '@/types/model-file-version'
import type { NoteActions } from './NotePins'
import { SEVERITY_CLASS, SEVERITY_TEXT, SOURCE_TEXT, isTyped, measureText, statusText } from './noteText'

type Filter = 'all' | NoteStatus
type SourceFilter = 'all' | NoteSource
type SeverityFilter = 'all' | NoteSeverity

interface NotesPanelProps extends Omit<NoteActions, 'onMove'> {
  notes: FileNote[]
  canWrite: boolean
  includeArchived: boolean
  onIncludeArchivedChange: (value: boolean) => void
  onReopen: (note: FileNote) => void
  /** Set an open note aside with a written reason (spec 009, clarification Q2). */
  onDismiss?: (note: FileNote, reason: string) => void
}

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'carried_forward', label: 'Carried' },
  { value: 'dismissed', label: 'Dismissed' },
]

const SOURCE_FILTERS: { value: SourceFilter; label: string }[] = [
  { value: 'all', label: 'Any source' },
  { value: 'person', label: 'People' },
  { value: 'preflight', label: 'Preflight' },
]

const SEVERITY_FILTERS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: 'Any severity' },
  { value: 'failure', label: 'Failures' },
  { value: 'warning', label: 'Warnings' },
]

function FilterGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((f) => (
        <Button
          key={f.value}
          type="button"
          size="sm"
          variant={value === f.value ? 'default' : 'outline'}
          className="h-7 px-2 text-xs"
          aria-pressed={value === f.value}
          onClick={() => onChange(f.value)}
        >
          {f.label}
        </Button>
      ))}
    </div>
  )
}

function DismissForm({ onSave, onCancel }: { onSave: (reason: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState('')
  const trimmed = reason.trim()
  return (
    <div className="mt-2 space-y-1">
      <Textarea
        aria-label="Why is this note dismissed?"
        placeholder="Why is this alert accepted? (required)"
        value={reason}
        maxLength={2000}
        onChange={(e) => setReason(e.target.value)}
        className="min-h-16 text-sm"
      />
      <div className="flex gap-1">
        <Button size="sm" className="h-7 text-xs" disabled={!trimmed} onClick={() => onSave(trimmed)}>
          Dismiss note
        </Button>
        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

export function NotesPanel({
  notes,
  canWrite,
  includeArchived,
  onIncludeArchivedChange,
  onResolve,
  onCarryForward,
  onReopen,
  onDismiss,
}: NotesPanelProps) {
  const [filter, setFilter] = useState<Filter>('all')
  const [source, setSource] = useState<SourceFilter>('all')
  const [severity, setSeverity] = useState<SeverityFilter>('all')
  const [dismissing, setDismissing] = useState<string | null>(null)
  const typed = notes.some(isTyped)
  const shown = notes.filter(
    (n) =>
      (filter === 'all' || n.status === filter) &&
      (source === 'all' || n.source === source) &&
      (severity === 'all' || n.severity === severity)
  )

  return (
    <section aria-label="Notes" className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Notes</h3>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Switch
            checked={includeArchived}
            onCheckedChange={onIncludeArchivedChange}
            aria-label="Show archived notes"
          />
          Archived
        </label>
      </div>
      <FilterGroup<Filter> label="Filter notes" options={FILTERS} value={filter} onChange={setFilter} />
      {typed && (
        <>
          <FilterGroup<SourceFilter> label="Filter by source" options={SOURCE_FILTERS} value={source} onChange={setSource} />
          <FilterGroup<SeverityFilter>
            label="Filter by severity"
            options={SEVERITY_FILTERS}
            value={severity}
            onChange={setSeverity}
          />
        </>
      )}

      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {notes.length === 0 ? 'No notes yet. Choose "Add note", then click the part.' : 'No notes match.'}
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map((note) => {
            const measure = measureText(note)
            return (
              <li
                key={note.id}
                className={[
                  'rounded-md border p-2 text-sm',
                  note.ghost ? 'border-dashed border-amber-400 bg-amber-50/60 dark:bg-amber-950/30' : '',
                ].join(' ')}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">#{note.number}</span>
                  <Badge variant={note.status === 'open' ? 'default' : 'secondary'}>
                    {note.ghost ? 'Earlier version' : statusText(note)}
                  </Badge>
                  {note.severity !== 'info' && (
                    <Badge variant="outline" className={SEVERITY_CLASS[note.severity]}>
                      {SEVERITY_TEXT[note.severity]}
                    </Badge>
                  )}
                  {note.source !== 'person' && <Badge variant="outline">{SOURCE_TEXT[note.source]}</Badge>}
                  {note.layer !== null && <span className="text-xs text-muted-foreground">Layer {note.layer + 1}</span>}
                  {note.archived_at && <Badge variant="outline">Archived</Badge>}
                </div>
                <p className="mt-1 whitespace-pre-wrap break-words">{note.text}</p>
                {(note.rule_id || measure) && (
                  <p className="mt-1 break-words text-xs">
                    {note.rule_id && <code className="rounded bg-muted px-1">{note.rule_id}</code>}
                    {note.rule_id && measure && ' · '}
                    {measure}
                  </p>
                )}
                {note.dismissal_reason && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {note.status === 'dismissed' ? 'Dismissed' : 'Was dismissed'}: {note.dismissal_reason}
                    {note.dismissed_by && <> ({note.dismissed_by.name})</>}
                  </p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {note.author?.name ?? 'Unknown'} · {new Date(note.created_at).toLocaleDateString()}
                </p>
                {canWrite && !note.archived_at && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {note.ghost ? (
                      <>
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onResolve(note)}>
                          Resolved in this version
                        </Button>
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onCarryForward(note)}>
                          Carry forward
                        </Button>
                      </>
                    ) : note.status === 'open' ? (
                      <>
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onResolve(note)}>
                          Resolve
                        </Button>
                        {onDismiss && dismissing !== note.id && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs"
                            onClick={() => setDismissing(note.id)}
                          >
                            Dismiss
                          </Button>
                        )}
                      </>
                    ) : note.status === 'resolved' || note.status === 'dismissed' ? (
                      <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onReopen(note)}>
                        Reopen
                      </Button>
                    ) : null}
                  </div>
                )}
                {onDismiss && dismissing === note.id && (
                  <DismissForm
                    onCancel={() => setDismissing(null)}
                    onSave={(reason) => {
                      onDismiss(note, reason)
                      setDismissing(null)
                    }}
                  />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
