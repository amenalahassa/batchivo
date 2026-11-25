/** A job's status, with a spinner while it runs (spec 008). */
import { Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { JobStatus } from '@/types/genai'
import { STATUS_LABELS } from './genaiText'

const VARIANTS: Record<JobStatus, 'secondary' | 'success' | 'destructive' | 'outline'> = {
  queued: 'outline',
  running: 'secondary',
  succeeded: 'success',
  failed: 'destructive',
  canceled: 'outline',
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const active = status === 'queued' || status === 'running'
  return (
    <Badge variant={VARIANTS[status]} className="gap-1" role="status">
      {active && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
      {STATUS_LABELS[status]}
    </Badge>
  )
}
