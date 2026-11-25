/**
 * Queue profitability — which queued job pays most for the machine time it
 * takes (T234, FR-043, US7).
 *
 * The ranking existed in `PrintQueueService` and had neither a route nor a
 * screen, so the decision US7 is named for -- what to print next -- was made
 * without it.
 */

import { AppLayout } from '@/components/layout/AppLayout'
import { QueueProfitabilityPanel } from '@/components/pricing/QueueProfitabilityPanel'

export function QueueProfitability() {
  return (
    <AppLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Queue</h1>
          <p className="text-muted-foreground">
            What each queued job earns per hour of the machine, to decide what to print next.
          </p>
        </div>

        <QueueProfitabilityPanel />
      </div>
    </AppLayout>
  )
}
