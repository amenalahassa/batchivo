/**
 * One idea: header, composer, timeline and gallery (spec 007, US2, US3).
 */
import { Link, useParams } from '@tanstack/react-router'
import { Sparkles } from 'lucide-react'

import { IdeaComposer } from '@/components/ideas/IdeaComposer'
import { GenerateDialog } from '@/components/genai/GenerateDialog'
import { JobHistory } from '@/components/genai/JobHistory'
import { useGenAIRoles } from '@/components/genai/useGenAIRoles'
import { AuthImage } from '@/components/ideas/AuthImage'
import { IdeaGallery } from '@/components/ideas/IdeaGallery'
import { IdeaHeader } from '@/components/ideas/IdeaHeader'
import { IdeaTimeline } from '@/components/ideas/IdeaTimeline'
import { useIdeaRoles } from '@/components/ideas/useIdeaRoles'
import { AppLayout } from '@/components/layout/AppLayout'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIdea } from '@/hooks/useIdeas'
import { useIdeaEntries } from '@/hooks/useIdeas'
import { apiErrorStatus } from '@/lib/apiError'

export function IdeaDetail({ ideaId }: { ideaId: string }) {
  const { canWrite, canCreateProduct } = useIdeaRoles()
  const { idea, isLoading, error } = useIdea(ideaId)
  const { canGenerate } = useGenAIRoles()
  const { entries } = useIdeaEntries(ideaId)

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

  // The idea's own pictures, offered as references for a concept (spec 008, T039).
  const referenceImages = entries
    .filter((e) => (e.kind === 'image' || e.kind === 'sketch') && !e.archived && e.thumbnail_path)
    .map((e) => ({
      ref: { type: 'idea_entry' as const, id: e.id },
      label: e.original_filename ?? (e.kind === 'sketch' ? 'Sketch' : 'Image'),
      preview: (
        <AuthImage
          path={e.thumbnail_path}
          alt={e.original_filename ?? e.kind}
          className="h-20 w-20 rounded"
        />
      ),
    }))
  const conceptPrompt = [idea.title, idea.summary].filter(Boolean).join('. ')
  const generateConcept = canGenerate ? (
    <GenerateDialog
      capability="concept_image"
      title="Generate concept"
      target={{ type: 'idea', id: idea.id }}
      adoptTarget={{ type: 'idea', id: idea.id }}
      defaultInputs={{ prompt: conceptPrompt }}
      inputAssets={referenceImages}
      trigger={
        <Button size="sm" variant="outline">
          <Sparkles className="mr-1 h-4 w-4" aria-hidden />
          Generate concept
        </Button>
      }
    />
  ) : null

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
          <TabsTrigger value="ai">AI</TabsTrigger>
        </TabsList>
        <TabsContent value="timeline" className="space-y-4">
          {canWrite && !idea.archived && (
            <IdeaComposer
              ideaId={idea.id}
              currentIteration={idea.current_iteration}
              extraActions={generateConcept}
            />
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
        <TabsContent value="ai">
          <JobHistory targetType="idea" targetId={idea.id} />
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
