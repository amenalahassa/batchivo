/**
 * "From idea" on a model or product made from an idea (spec 007, FR-027).
 */
import { Link } from '@tanstack/react-router'
import { Lightbulb } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

interface FromIdeaLinkProps {
  ideaId?: string | null
  title?: string | null
  archived?: boolean | null
}

export function FromIdeaLink({ ideaId, title, archived }: FromIdeaLinkProps) {
  if (!ideaId) return null
  return (
    <p className="mt-1 flex items-center gap-1 text-sm text-muted-foreground">
      <Lightbulb className="h-4 w-4" aria-hidden />
      From idea:{' '}
      <Link to="/ideas/$ideaId" params={{ ideaId }} className="text-primary underline">
        {title ?? 'Idea'}
      </Link>
      {archived && <Badge variant="outline">Archived</Badge>}
    </p>
  )
}
