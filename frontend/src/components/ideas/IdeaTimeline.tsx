/**
 * An idea's entries grouped by iteration, latest first (spec 007, FR-017).
 *
 * The backend already orders entries by iteration, pinned, then newest; this
 * groups them without reordering.
 */
import { useState } from 'react'

import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useIdeaEntries, useUpdateEntry, useUpdateIdea } from '@/hooks/useIdeas'

import { IdeaEntryItem } from './IdeaEntryItem'
import { groupByIteration } from './ideaText'

interface IdeaTimelineProps {
  ideaId: string
  coverEntryId: string | null
  canWrite: boolean
}

export function IdeaTimeline({ ideaId, coverEntryId, canWrite }: IdeaTimelineProps) {
  const [showArchived, setShowArchived] = useState(false)
  const { entries, isLoading } = useIdeaEntries(ideaId, showArchived)
  const updateEntry = useUpdateEntry(ideaId)
  const updateIdea = useUpdateIdea(ideaId)
  const groups = groupByIteration(entries)

  return (
    <section className="space-y-4" aria-label="Timeline">
      <div className="flex items-center justify-end gap-2">
        <Switch
          id="show-archived-entries"
          checked={showArchived}
          onCheckedChange={setShowArchived}
        />
        <Label htmlFor="show-archived-entries">Show archived</Label>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!isLoading && groups.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing yet. Add a note, a link or an image.
        </p>
      )}
      {groups.map(([iteration, items]) => (
        <div key={iteration} className="space-y-2">
          <h3 className="text-sm font-semibold">Iteration {iteration}</h3>
          <ul className="space-y-2">
            {items.map((entry) => (
              <IdeaEntryItem
                key={entry.id}
                entry={entry}
                canWrite={canWrite}
                isCover={entry.id === coverEntryId}
                onUpdate={(entryId, data) => updateEntry.mutate({ entryId, ...data })}
                onSetCover={(entryId) => updateIdea.mutate({ cover_entry_id: entryId })}
              />
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
