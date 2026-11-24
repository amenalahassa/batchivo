/**
 * An idea on the board: cover, title, score, tags, and a menu to move it (spec 007).
 */
import { Link } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import type { IdeaStatus, IdeaSummary } from '@/types/idea'

import { AuthImage } from './AuthImage'
import { STATUS_LABELS, WRITABLE_STATUSES, scoreText } from './ideaText'

interface IdeaCardProps {
  idea: IdeaSummary
  canWrite: boolean
  onMove?: (ideaId: string, status: IdeaStatus) => void
}

export function IdeaCard({ idea, canWrite, onMove }: IdeaCardProps) {
  return (
    <article
      className="overflow-hidden rounded-md border bg-card text-sm shadow-sm"
      aria-label={idea.title}
    >
      {idea.cover_thumbnail_path && (
        <AuthImage path={idea.cover_thumbnail_path} alt={idea.title} className="h-28 w-full" />
      )}
      <div className="space-y-2 p-3">
        <Link
          to="/ideas/$ideaId"
          params={{ ideaId: idea.id }}
          className="block font-medium hover:underline"
        >
          {idea.title}
        </Link>
        <p className="text-xs text-muted-foreground">{scoreText(idea)}</p>
        {idea.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {idea.tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-[10px]">
                {tag}
              </Badge>
            ))}
          </div>
        )}
        {canWrite && onMove && (
          <select
            aria-label={`Move ${idea.title}`}
            className="h-7 w-full rounded border bg-background px-1 text-xs"
            value={idea.status === 'converted' ? '' : idea.status}
            onChange={(e) => onMove(idea.id, e.target.value as IdeaStatus)}
          >
            {idea.status === 'converted' && <option value="">Converted</option>}
            {WRITABLE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        )}
      </div>
    </article>
  )
}
