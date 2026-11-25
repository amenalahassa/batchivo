/**
 * Ideas by status, one column each, loaded page by page (spec 007, FR-008, FR-010).
 */
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useIdeas, useUpdateAnyIdea } from '@/hooks/useIdeas'
import type { IdeaStatus, WritableIdeaStatus } from '@/types/idea'

import { IdeaCard } from './IdeaCard'
import { BOARD_STATUSES, STATUS_LABELS } from './ideaText'

export const COLUMN_PAGE = 20

interface IdeaBoardProps {
  canWrite: boolean
  onNewIdea?: () => void
  onImport?: () => void
}

function IdeaColumn({
  status,
  canWrite,
  onNewIdea,
  onImport,
}: IdeaBoardProps & { status: IdeaStatus }) {
  const [limit, setLimit] = useState(COLUMN_PAGE)
  const { ideas, total, isLoading } = useIdeas({ status: [status], limit, skip: 0 })
  const move = useUpdateAnyIdea()

  return (
    <section
      aria-label={STATUS_LABELS[status]}
      className="flex w-64 shrink-0 flex-col gap-2 rounded-lg bg-muted/40 p-2"
    >
      <header className="flex items-center justify-between px-1 text-sm font-semibold">
        <span>{STATUS_LABELS[status]}</span>
        <span className="text-muted-foreground" aria-label={`${total} ideas`}>
          {total}
        </span>
      </header>
      {isLoading && <p className="px-1 text-xs text-muted-foreground">Loading…</p>}
      {!isLoading && total === 0 && status === 'inbox' && (
        <div className="space-y-2 rounded border border-dashed p-3 text-xs text-muted-foreground">
          <p>No idea yet.</p>
          {canWrite && (
            <div className="flex flex-wrap gap-2">
              {onNewIdea && (
                <Button size="sm" variant="outline" onClick={onNewIdea}>
                  New idea
                </Button>
              )}
              {onImport && (
                <Button size="sm" variant="outline" onClick={onImport}>
                  Import report
                </Button>
              )}
            </div>
          )}
        </div>
      )}
      {ideas.map((idea) => (
        <IdeaCard
          key={idea.id}
          idea={idea}
          canWrite={canWrite}
          onMove={(ideaId, next) =>
            next !== status && move.mutate({ ideaId, status: next as WritableIdeaStatus })
          }
        />
      ))}
      {ideas.length < total && (
        <Button variant="ghost" size="sm" onClick={() => setLimit(limit + COLUMN_PAGE)}>
          Load more
        </Button>
      )}
    </section>
  )
}

export function IdeaBoard(props: IdeaBoardProps) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-4" role="list" aria-label="Ideas board">
      {BOARD_STATUSES.map((status) => (
        <div role="listitem" key={status}>
          <IdeaColumn status={status} {...props} />
        </div>
      ))}
    </div>
  )
}
