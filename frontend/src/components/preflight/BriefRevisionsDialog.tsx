/**
 * Earlier intents, risk parts and plans of a brief, newest first, read-only (spec 009, Q1).
 */
import { useState } from 'react'

import { Markdown } from '@/components/ideas/Markdown'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useBriefRevisions } from '@/hooks/usePreflight'
import type { DesignBriefRevision, RevisionPart } from '@/types/preflight'
import { RISK_TEXT, blockText } from './preflightText'

const PART_TEXT: Record<RevisionPart, string> = { intent: 'Intent', risk: 'Risk', plan: 'Plan' }

function RevisionContent({ revision }: { revision: DesignBriefRevision }) {
  const content = revision.content as Record<string, unknown>
  if (revision.part === 'plan') return <Markdown>{String(content.plan_md ?? '')}</Markdown>
  if (revision.part === 'risk') {
    const klass = content.risk_class as keyof typeof RISK_TEXT | null
    return (
      <div className="space-y-1">
        <p className="text-sm">Class: {klass ? RISK_TEXT[klass] ?? klass : 'not assessed'}</p>
        <Markdown>{String(content.risk_md ?? '')}</Markdown>
      </div>
    )
  }
  return <pre className="overflow-x-auto whitespace-pre-wrap text-xs">{blockText(content)}</pre>
}

interface BriefRevisionsDialogProps {
  briefId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function BriefRevisionsDialog({ briefId, open, onOpenChange }: BriefRevisionsDialogProps) {
  const [part, setPart] = useState<RevisionPart | undefined>(undefined)
  const [shown, setShown] = useState<string | null>(null)
  const { revisions, isLoading } = useBriefRevisions(briefId, part, open)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Brief history</DialogTitle>
          <DialogDescription>Every saved intent, risk part and plan, newest first. Read only.</DialogDescription>
        </DialogHeader>
        <div role="group" aria-label="Filter revisions" className="flex flex-wrap gap-1">
          {([undefined, 'intent', 'risk', 'plan'] as const).map((value) => (
            <Button
              key={value ?? 'all'}
              size="sm"
              variant={part === value ? 'default' : 'outline'}
              className="h-7 text-xs"
              aria-pressed={part === value}
              onClick={() => setPart(value)}
            >
              {value ? PART_TEXT[value] : 'All'}
            </Button>
          ))}
        </div>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : revisions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No earlier versions yet.</p>
        ) : (
          <ul className="space-y-2">
            {revisions.map((revision) => (
              <li key={revision.id} className="rounded-md border p-2">
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center justify-between gap-2 text-left text-sm"
                  aria-expanded={shown === revision.id}
                  onClick={() => setShown(shown === revision.id ? null : revision.id)}
                >
                  <span className="font-medium">{PART_TEXT[revision.part]}</span>
                  <span className="text-xs text-muted-foreground">
                    {revision.author?.name ?? 'Unknown'} · {new Date(revision.created_at).toLocaleString()}
                  </span>
                </button>
                {shown === revision.id && (
                  <div className="mt-2 border-t pt-2">
                    <RevisionContent revision={revision} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
