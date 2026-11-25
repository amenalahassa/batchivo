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
  Box,
  Copy,
  Wand2,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { AIBadge } from '@/components/genai/AIBadge'
import { GenerateDialog } from '@/components/genai/GenerateDialog'
import { JobDetails } from '@/components/genai/JobHistory'
import { MeshPreview } from '@/components/genai/MeshPreview'
import { useGenAIRoles } from '@/components/genai/useGenAIRoles'
import { useGenerationJob } from '@/hooks/useGenAI'
import type { EntryKind, IdeaEntry, IdeaEntryUpdate } from '@/types/idea'

import { AuthImage } from './AuthImage'
import { ImageViewer } from './ImageViewer'
import { Markdown } from './Markdown'
import { KIND_LABELS } from './ideaText'

/** Preset instruction of the "Variations" action (spec 008, T039). */
const VARIATION_INSTRUCTION =
  'Make a variation of this design, keeping its function and proportions'

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
  const [madeOpen, setMadeOpen] = useState(false)
  const { canGenerate } = useGenAIRoles()
  const isGenerated = entry.kind === 'generation'
  const hasGeneratedImage = isGenerated && Boolean(entry.thumbnail_path)
  // A generation entry's job: how it was made, and its mesh when it has no image.
  const { job } = useGenerationJob(isGenerated ? entry.generation_job_id : null)
  const meshOutput =
    isGenerated && !entry.thumbnail_path
      ? job?.outputs.find(
          (output) =>
            output.kind === 'mesh' &&
            output.adoptions.some((adoption) => adoption.idea_entry_id === entry.id)
        )
      : undefined
  const showAIActions = (isImage || hasGeneratedImage) && canGenerate && canWrite && !entry.archived
  const aiInput = [
    {
      ref: { type: 'idea_entry' as const, id: entry.id },
      label,
      preview: <AuthImage path={entry.thumbnail_path} alt={label} className="h-20 w-20 rounded" />,
    },
  ]
  const ideaTarget = { type: 'idea' as const, id: entry.idea_id }

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
          {isGenerated && <AIBadge />}
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

      {hasGeneratedImage && (
        <button
          type="button"
          className="mt-2 block"
          aria-label={`Open ${label}`}
          onClick={() => setViewing(true)}
        >
          <AuthImage path={entry.thumbnail_path} alt={label} className="h-32 w-32 rounded" />
        </button>
      )}

      {meshOutput && (
        <MeshPreview
          path={meshOutput.file_path}
          filename={meshOutput.original_filename}
          className="mt-2 max-w-xs"
        />
      )}

      {showAIActions && (
        <div role="group" aria-label="AI actions" className="mt-2 flex flex-wrap gap-1">
          <GenerateDialog
            capability="image_edit"
            title="Edit with AI"
            target={ideaTarget}
            adoptTarget={ideaTarget}
            inputAssets={aiInput}
            trigger={
              <Button size="sm" variant="outline">
                <Wand2 className="mr-1 h-3 w-3" aria-hidden />
                Edit with AI
              </Button>
            }
          />
          <GenerateDialog
            capability="image_edit"
            title="Variations"
            target={ideaTarget}
            adoptTarget={ideaTarget}
            inputAssets={aiInput}
            defaultInputs={{ instruction: VARIATION_INSTRUCTION }}
            trigger={
              <Button size="sm" variant="outline">
                <Copy className="mr-1 h-3 w-3" aria-hidden />
                Variations
              </Button>
            }
          />
          <GenerateDialog
            capability="image_to_3d"
            title="Draft 3D shape"
            target={ideaTarget}
            adoptTarget={ideaTarget}
            inputAssets={aiInput}
            trigger={
              <Button size="sm" variant="outline">
                <Box className="mr-1 h-3 w-3" aria-hidden />
                Draft 3D shape
              </Button>
            }
          />
        </div>
      )}

      {isGenerated && job && (
        <Button
          size="sm"
          variant="link"
          className="mt-1 h-auto px-0 text-xs"
          onClick={() => setMadeOpen(true)}
        >
          How it was made
        </Button>
      )}

      {editing ? (
        <div className="mt-2 space-y-2">
          {entry.kind === 'link' && (
            <Input aria-label="Link" value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} />
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

      {hasGeneratedImage && (
        <ImageViewer
          path={viewing ? entry.image_path : null}
          title={label}
          onClose={() => setViewing(false)}
        />
      )}

      {isGenerated && job && (
        <Sheet open={madeOpen} onOpenChange={setMadeOpen}>
          <SheetContent className="overflow-y-auto">
            <JobDetails job={job} />
          </SheetContent>
        </Sheet>
      )}
    </li>
  )
}
