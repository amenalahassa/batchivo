/**
 * Ideas as a searchable, filterable, paginated table (spec 007, FR-009, FR-010).
 */
import { useCallback, useState } from 'react'
import { Link } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useIdeas, useUpdateAnyIdea } from '@/hooks/useIdeas'
import type { IdeaListParams } from '@/types/idea'

import { IdeaFilters } from './IdeaFilters'
import { SOURCE_LABELS, STATUS_LABELS, scoreText } from './ideaText'

export const LIST_PAGE = 25

export function IdeaList({ canWrite }: { canWrite: boolean }) {
  const [filters, setFilters] = useState<IdeaListParams>({ sort: 'updated', archived: 'false' })
  const [page, setPage] = useState(0)
  const { ideas, total, isLoading, error } = useIdeas({
    ...filters,
    skip: page * LIST_PAGE,
    limit: LIST_PAGE,
  })
  const restore = useUpdateAnyIdea()
  const totalPages = Math.max(1, Math.ceil(total / LIST_PAGE))

  const changeFilters = useCallback((next: IdeaListParams) => {
    setFilters(next)
    setPage(0)
  }, [])

  return (
    <div className="space-y-3">
      <IdeaFilters value={filters} onChange={changeFilters} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          Ideas could not be loaded.
        </p>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Score</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Tags</TableHead>
            <TableHead>Updated</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && (
            <TableRow>
              <TableCell colSpan={7}>Loading…</TableCell>
            </TableRow>
          )}
          {!isLoading && ideas.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} className="text-muted-foreground">
                No idea matches.
              </TableCell>
            </TableRow>
          )}
          {ideas.map((idea) => (
            <TableRow key={idea.id}>
              <TableCell>
                <Link
                  to="/ideas/$ideaId"
                  params={{ ideaId: idea.id }}
                  className="font-medium hover:underline"
                >
                  {idea.title}
                </Link>
                {idea.archived && (
                  <Badge variant="outline" className="ml-2">
                    Archived
                  </Badge>
                )}
              </TableCell>
              <TableCell>{STATUS_LABELS[idea.status]}</TableCell>
              <TableCell>{scoreText(idea)}</TableCell>
              <TableCell>{SOURCE_LABELS[idea.source]}</TableCell>
              <TableCell>{idea.tags.join(', ')}</TableCell>
              <TableCell>{new Date(idea.updated_at).toLocaleDateString()}</TableCell>
              <TableCell>
                {idea.archived && canWrite && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => restore.mutate({ ideaId: idea.id, archived: false })}
                  >
                    Restore
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {total > LIST_PAGE && (
        <div className="flex items-center justify-between text-sm">
          <span>
            Showing {page * LIST_PAGE + 1} to {Math.min((page + 1) * LIST_PAGE, total)} of {total}
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </Button>
            <span>
              {page + 1} / {totalPages}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= totalPages - 1}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
