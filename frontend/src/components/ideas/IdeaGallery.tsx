/**
 * Every image and sketch of an idea, across iterations (spec 007, FR-019).
 */
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { useIdeaEntries } from '@/hooks/useIdeas'
import type { IdeaEntry } from '@/types/idea'

import { AuthImage } from './AuthImage'
import { ImageViewer } from './ImageViewer'
import { KIND_LABELS } from './ideaText'

export function IdeaGallery({ ideaId }: { ideaId: string }) {
  const { entries, isLoading } = useIdeaEntries(ideaId, false)
  const [open, setOpen] = useState<IdeaEntry | null>(null)
  const images = entries.filter(
    (e) => (e.kind === 'image' || e.kind === 'sketch') && !e.archived && e.thumbnail_path
  )

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (images.length === 0)
    return <p className="text-sm text-muted-foreground">No image yet.</p>

  return (
    <>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Gallery">
        {images.map((entry) => {
          const label = entry.original_filename ?? KIND_LABELS[entry.kind]
          return (
            <li key={entry.id} className="space-y-1">
              <button
                type="button"
                className="block w-full"
                aria-label={`Open ${label}`}
                onClick={() => setOpen(entry)}
              >
                <AuthImage path={entry.thumbnail_path} alt={label} className="h-36 w-full rounded" />
              </button>
              <div className="flex gap-1">
                <Badge variant="secondary">Iteration {entry.iteration}</Badge>
                {entry.kind === 'sketch' && <Badge variant="outline">Sketch</Badge>}
              </div>
            </li>
          )
        })}
      </ul>
      <ImageViewer
        path={open?.image_path ?? null}
        title={open?.original_filename ?? 'Image'}
        onClose={() => setOpen(null)}
      />
    </>
  )
}
