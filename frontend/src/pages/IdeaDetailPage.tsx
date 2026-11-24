/**
 * One idea: header, composer, timeline and gallery (spec 007, US2, US3).
 */
import { Link, useParams } from '@tanstack/react-router'

import { IdeaComposer } from '@/components/ideas/IdeaComposer'
import { IdeaGallery } from '@/components/ideas/IdeaGallery'
import { IdeaHeader } from '@/components/ideas/IdeaHeader'
import { IdeaTimeline } from '@/components/ideas/IdeaTimeline'
import { useIdeaRoles } from '@/components/ideas/useIdeaRoles'
import { AppLayout } from '@/components/layout/AppLayout'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIdea } from '@/hooks/useIdeas'
import { apiErrorStatus } from '@/lib/apiError'

export function IdeaDetail({ ideaId }: { ideaId: string }) {
  const { canWrite, canCreateProduct } = useIdeaRoles()
  const { idea, isLoading, error } = useIdea(ideaId)

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (error || !idea) {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold">
          {apiErrorStatus(error) === 404 || !error ? 'Idea not found' : 'The idea could not be loaded'}
        </h1>
        <Link to="/ideas" className="text-primary underline">
          Back to ideas
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Link to="/ideas" className="text-sm text-muted-foreground hover:underline">
        ← Ideas
      </Link>
      <IdeaHeader idea={idea} canWrite={canWrite} canCreateProduct={canCreateProduct} />
      <Tabs defaultValue="timeline">
        <TabsList>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="gallery">Gallery</TabsTrigger>
        </TabsList>
        <TabsContent value="timeline" className="space-y-4">
          {canWrite && !idea.archived && (
            <IdeaComposer ideaId={idea.id} currentIteration={idea.current_iteration} />
          )}
          <IdeaTimeline
            ideaId={idea.id}
            coverEntryId={idea.cover_entry_id}
            canWrite={canWrite && !idea.archived}
          />
        </TabsContent>
        <TabsContent value="gallery">
          <IdeaGallery ideaId={idea.id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export function IdeaDetailPage() {
  const { ideaId } = useParams({ from: '/ideas/$ideaId' })
  return (
    <AppLayout>
      <IdeaDetail ideaId={ideaId} />
    </AppLayout>
  )
}
