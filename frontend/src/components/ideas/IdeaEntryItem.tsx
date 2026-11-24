/**
 * One timeline entry: its text, link or image, and what can be done to it (spec 007,
 * FR-011, FR-013, FR-016, FR-018).
 */
import { useState } from 'react'
import {
  Archive,
  ArchiveRestore,
  Image as ImageIcon,
  Link2,
  NotebookPen,
  Pencil,
  Pin,
  PinOff,
  Ruler,
  Sparkles,
  Star,
  Gavel,
  PenTool,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { EntryKind, IdeaEntry, IdeaEntryUpdate } from '@/types/idea'

import { AuthImage } from './AuthImage'
import { ImageViewer } from './ImageViewer'
import { Markdown } from './Markdown'
import { KIND_LABELS } from './ideaText'

const KIND_ICONS: Record<EntryKind, typeof NotebookPen> = {
  note: NotebookPen,
  image: ImageIcon,
  link: Link2,
  sketch: PenTool,
  measurement: Ruler,
  decision: Gavel,
  generation: Sparkles,
}

interface IdeaEntryItemProps {
  entry: IdeaEntry
  canWrite: boolean
  isCover?: boolean
  onUpdate: (entryId: string, data: IdeaEntryUpdate) => void
  onSetCover?: (entryId: string | null) => void
}

export function IdeaEntryItem({
  entry,
  canWrite,
  isCover,
  onUpdate,
  onSetCover,
}: IdeaEntryItemProps) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(entry.body ?? '')
  const [linkUrl, setLinkUrl] = useState(entry.link_url ?? '')
  const [viewing, setViewing] = useState(false)
  const Icon = KIND_ICONS[entry.kind]
  const isImage = entry.kind === 'image' || entry.kind === 'sketch'
  const label = entry.original_filename ?? KIND_LABELS[entry.kind]

  function save() {
    const data: IdeaEntryUpdate = { body: body.trim() || null }
    if (entry.kind === 'link') data.link_url = linkUrl.trim() || null
    onUpdate(entry.id, data)
    setEditing(false)
  }

  return (
    <li
      className={`rounded-md border p-3 text-sm ${entry.archived ? 'opacity-60' : ''}`}
      aria-label={`${KIND_LABELS[entry.kind]} entry`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Icon className="h-4 w-4" aria-hidden />
          <span className="font-medium text-foreground">{KIND_LABELS[entry.kind]}</span>
          {entry.pinned && <Badge variant="secondary">Pinned</Badge>}
          {isCover && <Badge variant="secondary">Cover</Badge>}
          {entry.archived && <Badge variant="outline">Archived</Badge>}
          <span>
            {entry.author?.name ?? 'Unknown'} · {new Date(entry.created_at).toLocaleString()}
          </span>
          {entry.edited_at && <span>(edited)</span>}
        </div>
        {canWrite && (
          <div className="flex items-center gap-1">
            {!entry.archived && entry.kind !== 'generation' && (
              <Button
                size="icon"
                variant="ghost"
                aria-label="Edit entry"
                onClick={() => setEditing(!editing)}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            )}
            {!entry.archived && (
              <Button
                size="icon"
                variant="ghost"
                aria-label={entry.pinned ? 'Unpin entry' : 'Pin entry'}
                onClick={() => onUpdate(entry.id, { pinned: !entry.pinned })}
              >
                {entry.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
              </Button>
            )}
            {isImage && !entry.archived && onSetCover && (
              <Button
                size="icon"
                variant="ghost"
                aria-label={isCover ? 'Clear cover' : 'Set as cover'}
                onClick={() => onSetCover(isCover ? null : entry.id)}
              >
                <Star className={`h-4 w-4 ${isCover ? 'fill-current' : ''}`} />
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              aria-label={entry.archived ? 'Restore entry' : 'Archive entry'}
              onClick={() => onUpdate(entry.id, { archived: !entry.archived })}
            >
              {entry.archived ? (
                <ArchiveRestore className="h-4 w-4" />
              ) : (
                <Archive className="h-4 w-4" />
              )}
            </Button>
          </div>
        )}
      </div>

      {isImage && entry.thumbnail_path && (
        <button
          type="button"
          className="mt-2 block"
          aria-label={`Open ${label}`}
          onClick={() => setViewing(true)}
        >
          <AuthImage path={entry.thumbnail_path} alt={label} className="h-32 w-32 rounded" />
        </button>
      )}

      {editing ? (
        <div className="mt-2 space-y-2">
          {entry.kind === 'link' && (
            <Input
              aria-label="Link"
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
            />
          )}
          <Textarea
            aria-label="Entry text"
            value={body}
            rows={3}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={save}>
              Save
            </Button>
          </div>
        </div>
      ) : (
        <>
          {entry.kind === 'link' && entry.link_url && (
            <a
              href={entry.link_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 block break-all text-primary underline"
            >
              {entry.link_url}
            </a>
          )}
          {entry.body && <Markdown className="mt-2">{entry.body}</Markdown>}
        </>
      )}

      {isImage && (
        <ImageViewer
          path={viewing ? entry.image_path : null}
          title={label}
          onClose={() => setViewing(false)}
        />
      )}
    </li>
  )
}
