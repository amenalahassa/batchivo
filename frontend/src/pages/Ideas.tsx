/**
 * Ideas: the board and the list of product ideas (spec 007, US1, US4).
 */
import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Lightbulb } from 'lucide-react'

import { IdeaBoard } from '@/components/ideas/IdeaBoard'
import { IdeaForm } from '@/components/ideas/IdeaForm'
import { IdeaList } from '@/components/ideas/IdeaList'
import { ImportReportDialog } from '@/components/ideas/ImportReportDialog'
import { useIdeaRoles } from '@/components/ideas/useIdeaRoles'
import { AppLayout } from '@/components/layout/AppLayout'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useCreateIdea } from '@/hooks/useIdeas'
import { apiErrorDetail } from '@/lib/apiError'

export function IdeasView() {
  const { canWrite } = useIdeaRoles()
  const navigate = useNavigate()
  const create = useCreateIdea()
  const [view, setView] = useState<'board' | 'list'>('board')
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Lightbulb className="h-6 w-6" aria-hidden />
          Ideas
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="View" className="flex">
            <Button
              size="sm"
              variant={view === 'board' ? 'default' : 'outline'}
              aria-pressed={view === 'board'}
              onClick={() => setView('board')}
            >
              Board
            </Button>
            <Button
              size="sm"
              variant={view === 'list' ? 'default' : 'outline'}
              aria-pressed={view === 'list'}
              onClick={() => setView('list')}
            >
              List
            </Button>
          </div>
          {canWrite && (
            <>
              <Button size="sm" variant="outline" onClick={() => setImporting(true)}>
                Import report
              </Button>
              <Button size="sm" onClick={() => setCreating(true)}>
                New idea
              </Button>
            </>
          )}
        </div>
      </div>

      {view === 'board' ? (
        <IdeaBoard
          canWrite={canWrite}
          onNewIdea={() => setCreating(true)}
          onImport={() => setImporting(true)}
        />
      ) : (
        <IdeaList canWrite={canWrite} />
      )}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>New idea</DialogTitle>
          </DialogHeader>
          <IdeaForm
            submitLabel="Create"
            isSubmitting={create.isPending}
            error={error}
            onCancel={() => setCreating(false)}
            onSubmit={(data) => {
              setError(null)
              create.mutate(data, {
                onSuccess: (idea) => {
                  setCreating(false)
                  navigate({ to: '/ideas/$ideaId', params: { ideaId: idea.id } })
                },
                onError: (err) => setError(apiErrorDetail(err)),
              })
            }}
          />
        </DialogContent>
      </Dialog>
      <ImportReportDialog open={importing} onClose={() => setImporting(false)} />
    </div>
  )
}

export function Ideas() {
  return (
    <AppLayout>
      <IdeasView />
    </AppLayout>
  )
}
