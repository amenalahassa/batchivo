/**
 * ModelCostProfileDialog — the item's cost profile, reachable from its page.
 *
 * `ModelCostProfileForm` knows how to read and write one item's operational
 * figures; it had no way in, which is the whole reason those figures sat at
 * their migration defaults everywhere. The door is on the model's own page
 * rather than in a global setting because each is a measurement of *this* part
 * (FR-007b).
 */

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ModelCostProfileForm } from './ModelCostProfileForm'

interface ModelCostProfileDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Null while no item is selected; the dialog then renders nothing. */
  modelId: string | null
  modelName?: string
  /** False for a viewer. A member may record a measurement (FR-007b). */
  canEdit?: boolean
}

export function ModelCostProfileDialog({
  open,
  onOpenChange,
  modelId,
  modelName,
  canEdit = true,
}: ModelCostProfileDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Cost profile{modelName ? ` — ${modelName}` : ''}</DialogTitle>
          <DialogDescription>
            These figures are measurements of this part, so they belong to it alone — and until
            they are recorded the engine costs it as though nothing is purged and nothing ever
            fails.
          </DialogDescription>
        </DialogHeader>

        {modelId ? (
          <ModelCostProfileForm modelId={modelId} canEdit={canEdit} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
