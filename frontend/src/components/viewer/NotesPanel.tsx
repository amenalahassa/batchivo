/**
 * The notes of a file, listed beside the viewer (spec 004, T052; FR-028).
 *
 * Readable and usable without the 3D view, at phone width: number, text,
 * status, author and date, a status filter and an archived toggle. An earlier
 * version's open note (a ghost) can be resolved here or carried forward.
 */
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import type { FileNote, NoteStatus } from '@/types/model-file-version'
import type { NoteActions } from './NotePins'
import { statusText } from './noteText'

type Filter = 'all' | NoteStatus

interface NotesPanelProps extends Omit<NoteActions, 'onMove'> {
  notes: FileNote[]
  canWrite: boolean
  includeArchived: boolean
  onIncludeArchivedChange: (value: boolean) => void
  onReopen: (note: FileNote) => void
}

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'carried_forward', label: 'Carried' },
]

export function NotesPanel({
  notes,
  canWrite,
  includeArchived,
  onIncludeArchivedChange,
  onResolve,
  onCarryForward,
  onReopen,
}: NotesPanelProps) {
  const [filter, setFilter] = useState<Filter>('all')
  const shown = notes.filter((n) => filter === 'all' || n.status === filter)

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
      <div role="group" aria-label="Filter notes" className="flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <Button
            key={f.value}
            type="button"
            size="sm"
            variant={filter === f.value ? 'default' : 'outline'}
            className="h-7 px-2 text-xs"
            aria-pressed={filter === f.value}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {notes.length === 0 ? 'No notes yet. Choose "Add note", then click the part.' : 'No notes match.'}
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map((note) => (
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
                {note.layer !== null && <span className="text-xs text-muted-foreground">Layer {note.layer + 1}</span>}
                {note.archived_at && <Badge variant="outline">Archived</Badge>}
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words">{note.text}</p>
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
                    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onResolve(note)}>
                      Resolve
                    </Button>
                  ) : note.status === 'resolved' ? (
                    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onReopen(note)}>
                      Reopen
                    </Button>
                  ) : null}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
