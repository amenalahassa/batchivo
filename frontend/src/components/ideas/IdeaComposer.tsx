/**
 * Add to an idea's current iteration: notes, links, measurements, decisions and
 * images by picker, drop or paste; start the next iteration (spec 007, FR-014, FR-015).
 */
import { useRef, useState, type ClipboardEvent, type DragEvent, type ReactNode } from 'react'
import axios from 'axios'
import { ImagePlus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useCreateEntry, useStartIteration, useUploadImages } from '@/hooks/useIdeas'
import { apiErrorDetail } from '@/lib/apiError'
import type { ImageEntryKind, RefusedFile, TextEntryKind } from '@/types/idea'

import { ACCEPTED_IMAGES, KIND_LABELS } from './ideaText'

const TEXT_KINDS: TextEntryKind[] = ['note', 'link', 'measurement', 'decision']

interface IdeaComposerProps {
  ideaId: string
  currentIteration: number
  /** Room for later features (AI generation, spec 008) to add their own actions. */
  extraActions?: ReactNode
}

/** The files the server refused, when it refused all of them. */
function refusedFrom(error: unknown): RefusedFile[] {
  if (!axios.isAxiosError(error)) return []
  const detail = (error.response?.data as { detail?: { refused?: RefusedFile[] } } | undefined)
    ?.detail
  return Array.isArray(detail?.refused) ? detail.refused : []
}

export function IdeaComposer({ ideaId, currentIteration, extraActions }: IdeaComposerProps) {
  const [kind, setKind] = useState<TextEntryKind>('note')
  const [body, setBody] = useState('')
  const [linkUrl, setLinkUrl] = useState('')
  const [imageKind, setImageKind] = useState<ImageEntryKind>('image')
  const [refused, setRefused] = useState<RefusedFile[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [iterationOpen, setIterationOpen] = useState(false)
  const [iterationNote, setIterationNote] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const createEntry = useCreateEntry(ideaId)
  const upload = useUploadImages(ideaId)
  const startIteration = useStartIteration(ideaId)

  function sendFiles(files: File[]) {
    if (files.length === 0) return
    setRefused([])
    setError(null)
    upload.mutate(
      { files, kind: imageKind },
      {
        onSuccess: (result) => setRefused(result.refused),
        onError: (err) => {
          const list = refusedFrom(err)
          setRefused(list)
          if (list.length === 0) setError(apiErrorDetail(err))
        },
      }
    )
  }

  function submit() {
    setError(null)
    if (!body.trim() && kind !== 'link') {
      setError('Write something first')
      return
    }
    if (kind === 'link' && !linkUrl.trim()) {
      setError('A link entry needs a link')
      return
    }
    createEntry.mutate(
      {
        kind,
        body: body.trim() || null,
        link_url: kind === 'link' ? linkUrl.trim() : null,
      },
      {
        onSuccess: () => {
          setBody('')
          setLinkUrl('')
        },
        onError: (err) => setError(apiErrorDetail(err)),
      }
    )
  }

  function handlePaste(event: ClipboardEvent) {
    const files = Array.from(event.clipboardData.files ?? [])
    if (files.length > 0) {
      event.preventDefault()
      sendFiles(files)
    }
    // Pasted text goes into the textarea by the browser's default behaviour.
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    sendFiles(Array.from(event.dataTransfer.files ?? []))
  }

  return (
    <section
      aria-label="Add to this idea"
      className={`space-y-3 rounded-md border p-3 ${dragging ? 'border-primary bg-primary/5' : ''}`}
      onPaste={handlePaste}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      data-testid="idea-composer"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Entry kind" className="flex gap-1">
          {TEXT_KINDS.map((k) => (
            <Button
              key={k}
              role="tab"
              aria-selected={kind === k}
              size="sm"
              variant={kind === k ? 'default' : 'outline'}
              onClick={() => setKind(k)}
            >
              {KIND_LABELS[k]}
            </Button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">Iteration {currentIteration}</span>
      </div>

      {kind === 'link' && (
        <Input
          aria-label="Link"
          placeholder="https://"
          value={linkUrl}
          onChange={(e) => setLinkUrl(e.target.value)}
        />
      )}
      <Textarea
        aria-label="Entry text"
        placeholder="Write in markdown, or paste or drop images here"
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={submit} disabled={createEntry.isPending}>
          Add {KIND_LABELS[kind].toLowerCase()}
        </Button>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept={ACCEPTED_IMAGES.join(',')}
          className="hidden"
          aria-label="Image files"
          onChange={(e) => {
            sendFiles(Array.from(e.target.files ?? []))
            e.target.value = ''
          }}
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => fileInput.current?.click()}
          disabled={upload.isPending}
        >
          <ImagePlus className="mr-1 h-4 w-4" aria-hidden />
          {upload.isPending ? 'Uploading…' : 'Add images'}
        </Button>
        <select
          aria-label="Image kind"
          className="h-8 rounded-md border bg-background px-2 text-xs"
          value={imageKind}
          onChange={(e) => setImageKind(e.target.value as ImageEntryKind)}
        >
          <option value="image">as images</option>
          <option value="sketch">as sketches</option>
        </select>
        <Button size="sm" variant="ghost" onClick={() => setIterationOpen(true)}>
          Start next iteration
        </Button>
        {extraActions}
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {refused.length > 0 && (
        <ul role="alert" aria-label="Refused files" className="text-sm text-destructive">
          {refused.map((r, i) => (
            <li key={`${r.filename}-${i}`}>
              {r.filename ?? 'File'}: {r.reason}
            </li>
          ))}
        </ul>
      )}

      <Dialog open={iterationOpen} onOpenChange={setIterationOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start iteration {currentIteration + 1}</DialogTitle>
          </DialogHeader>
          <Label htmlFor="iteration-note">Note (optional)</Label>
          <Textarea
            id="iteration-note"
            rows={3}
            value={iterationNote}
            onChange={(e) => setIterationNote(e.target.value)}
            placeholder="What changes in this iteration"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setIterationOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={startIteration.isPending}
              onClick={() =>
                startIteration.mutate(iterationNote.trim() || undefined, {
                  onSuccess: () => {
                    setIterationOpen(false)
                    setIterationNote('')
                  },
                })
              }
            >
              Start iteration
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
