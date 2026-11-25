/**
 * Numbered note pins on the part (spec 004, T051; FR-025 to FR-029a).
 *
 * Each pin is an HTML badge anchored to its 3D point, so it stays attached as
 * the view turns; hovering or focusing it shows the note. An earlier
 * version's open note is a faded "ghost" pin offering "Resolved in this
 * version" or "Carry forward". A note of this file can be moved: choose
 * "Move", then click the new spot on the part.
 *
 * Rendered inside the canvas, in the same group as the part, so positions are
 * the file's own coordinates.
 */
import { useState } from 'react'
import { Html } from '@react-three/drei'

import type { FileNote, Vector3 } from '@/types/model-file-version'
import { SEVERITY_TEXT, measureText, statusText } from './noteText'

export interface NoteActions {
  onResolve: (note: FileNote) => void
  onCarryForward: (note: FileNote) => void
  onMove: (note: FileNote) => void
}

interface NotePinsProps extends NoteActions {
  notes: FileNote[]
  canWrite: boolean
  /** A pin being placed: the draft text box sits at this point. */
  draft: { position: Vector3 } | null
  onDraftSave: (text: string) => void
  onDraftCancel: () => void
}

export function PinBadge({
  note,
  canWrite,
  onResolve,
  onCarryForward,
  onMove,
}: { note: FileNote; canWrite: boolean } & NoteActions) {
  const [open, setOpen] = useState(false)
  const done = note.status !== 'open'
  return (
    <div className="relative" onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        aria-label={`Note ${note.number}${note.ghost ? ' from an earlier version' : ''}`}
        onMouseEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        className={[
          'flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full text-xs font-semibold shadow',
          note.ghost
            ? 'border border-dashed border-amber-500 bg-amber-100/70 text-amber-800 opacity-70'
            : done
              ? 'bg-slate-400 text-white'
              : note.severity === 'failure'
                ? 'bg-red-600 text-white'
                : note.severity === 'warning'
                  ? 'bg-amber-500 text-white'
                  : 'bg-orange-500 text-white',
        ].join(' ')}
      >
        {note.number}
      </button>
      {open && (
        <div
          role="tooltip"
          className="absolute left-3 top-3 z-10 w-56 rounded-md border bg-popover p-2 text-xs text-popover-foreground shadow-md"
        >
          <p className="whitespace-pre-wrap">{note.text}</p>
          {(note.rule_id || measureText(note)) && (
            <p className="mt-1 break-words">
              {note.severity !== 'info' && <strong>{SEVERITY_TEXT[note.severity]} </strong>}
              {note.rule_id && <code>{note.rule_id}</code>}
              {note.rule_id && measureText(note) && ' · '}
              {measureText(note)}
            </p>
          )}
          <p className="mt-1 text-muted-foreground">
            {note.ghost ? 'Open in an earlier version' : statusText(note)}
            {note.author && <> · {note.author.name}</>}
          </p>
          {canWrite && (
            <div className="mt-2 flex flex-wrap gap-1">
              {note.ghost ? (
                <>
                  <button type="button" className="rounded border px-1.5 py-0.5" onClick={() => onResolve(note)}>
                    Resolved in this version
                  </button>
                  <button type="button" className="rounded border px-1.5 py-0.5" onClick={() => onCarryForward(note)}>
                    Carry forward
                  </button>
                </>
              ) : (
                note.status === 'open' && (
                  <>
                    <button type="button" className="rounded border px-1.5 py-0.5" onClick={() => onResolve(note)}>
                      Resolve
                    </button>
                    <button type="button" className="rounded border px-1.5 py-0.5" onClick={() => onMove(note)}>
                      Move
                    </button>
                  </>
                )
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function DraftNote({ onSave, onCancel }: { onSave: (text: string) => void; onCancel: () => void }) {
  const [text, setText] = useState('')
  return (
    <div className="w-56 rounded-md border bg-popover p-2 shadow-md">
      <textarea
        aria-label="Note text"
        autoFocus
        maxLength={2000}
        className="h-16 w-full rounded border bg-background p-1 text-xs"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="What needs changing here?"
      />
      <div className="mt-1 flex justify-end gap-1 text-xs">
        <button type="button" className="rounded px-1.5 py-0.5" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="rounded bg-primary px-1.5 py-0.5 text-primary-foreground disabled:opacity-50"
          disabled={!text.trim()}
          onClick={() => onSave(text.trim())}
        >
          Pin note
        </button>
      </div>
    </div>
  )
}

export function NotePins({ notes, canWrite, draft, onDraftSave, onDraftCancel, ...actions }: NotePinsProps) {
  return (
    <group>
      {notes.map((note) => (
        <Html key={note.id} position={note.position} zIndexRange={[20, 10]}>
          <PinBadge note={note} canWrite={canWrite} {...actions} />
        </Html>
      ))}
      {draft && (
        <Html position={draft.position} zIndexRange={[30, 20]}>
          <DraftNote onSave={onDraftSave} onCancel={onDraftCancel} />
        </Html>
      )}
    </group>
  )
}
