/**
 * Scenarios — what a price shock would do to the catalogue.
 *
 * "If filament rose 25%, which of my products stop paying?" is FR-044's
 * question. It spans every product, so it runs as a background job: the
 * request is acknowledged at once and the result arrives when it is ready
 * (FR-044a), with the job's state visible until then (FR-044b).
 *
 * `ScenarioRunPanel` does all of that. It had no route, which meant SC-006 —
 * "an operator requests a whole-catalogue shock in a single action" — had no
 * action to offer.
 */

import { AppLayout } from '@/components/layout/AppLayout'
import { ScenarioRunPanel } from '@/components/pricing/ScenarioRunPanel'

export function Scenarios() {
  return (
    <AppLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Scenarios</h1>
          <p className="text-muted-foreground">
            Ask what a price rise or a fee change would do to the whole catalogue, without
            changing a single stored figure.
          </p>
        </div>

        <ScenarioRunPanel />
      </div>
    </AppLayout>
  )
}
