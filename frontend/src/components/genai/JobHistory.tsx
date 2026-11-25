/**
 * Generation jobs of one idea, product or model, with how each was made (spec 008, US5).
 */
import { useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { useCancelJob, useGenerationJobs } from '@/hooks/useGenAI'
import { genaiApi } from '@/lib/api/genai'
import type { GenerationJob, TargetType } from '@/types/genai'
import { AddToProduct } from './AddToProduct'
import { AIBadge } from './AIBadge'
import { GenAIAssetImage } from './GenAIAssetImage'
import { JobStatusBadge } from './JobStatusBadge'
import { CAPABILITY_LABELS, failureMessage, usd } from './genaiText'
import { useGenAIRoles } from './useGenAIRoles'

interface JobHistoryProps {
  targetType: Exclude<TargetType, 'none'>
  targetId: string
}

function when(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

function costText(job: GenerationJob) {
  if (job.cost === null) return `≈ ${usd(job.estimated_cost)}`
  return job.cost_provenance === 'estimated' ? `≈ ${usd(job.cost)} (estimated)` : usd(job.cost)
}

export function JobHistory({ targetType, targetId }: JobHistoryProps) {
  const { jobs, isLoading } = useGenerationJobs({ target_type: targetType, target_id: targetId, limit: 50 })
  const { canGenerate } = useGenAIRoles()
  const cancel = useCancelJob()
  const [openId, setOpenId] = useState<string | null>(null)
  const open = jobs.find((j) => j.id === openId) ?? null

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading generations…</p>
  if (jobs.length === 0) {
    return <p className="text-sm text-muted-foreground">No AI generations yet.</p>
  }
  return (
    <>
      <ul className="divide-y rounded-md border" aria-label="AI generations">
        {jobs.map((job) => (
          <li key={job.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
            <JobStatusBadge status={job.status} />
            <span className="font-medium">{CAPABILITY_LABELS[job.capability] ?? job.capability_label}</span>
            <span className="text-muted-foreground">{costText(job)}</span>
            <span className="text-muted-foreground">{job.requested_by?.name ?? '—'}</span>
            <span className="text-muted-foreground">{when(job.created_at)}</span>
            <span className="ml-auto flex gap-2">
              {canGenerate && job.can_cancel && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={cancel.isPending}
                  onClick={() => cancel.mutate(job.id)}
                >
                  Cancel
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => setOpenId(job.id)}>
                How it was made
              </Button>
            </span>
            {job.status === 'failed' && (
              <p className="w-full text-xs text-destructive">{failureMessage(job.error_code, job.error)}</p>
            )}
          </li>
        ))}
      </ul>
      <Sheet open={Boolean(open)} onOpenChange={(next) => !next && setOpenId(null)}>
        <SheetContent className="overflow-y-auto">
          {open && <JobDetails job={open} />}
        </SheetContent>
      </Sheet>
    </>
  )
}

/** Thumbnails of the images a job was given (stored as generation asset ids). */
function InputImages({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <>—</>
  return (
    <ul className="grid grid-cols-4 gap-2" aria-label="Input images">
      {ids.map((id, index) => (
        <li key={id}>
          <GenAIAssetImage
            path={genaiApi.assetFilePath(id, 'thumb')}
            alt={`Input image ${index + 1}`}
            className="aspect-square w-full rounded-md border"
          />
        </li>
      ))}
    </ul>
  )
}

const TARGET_LABELS: Record<TargetType, string> = {
  idea: 'Idea',
  product: 'Product',
  model: 'Model',
  none: 'None',
}

/** What the job was made for, linked to its page when it has one. */
function TargetValue({ target }: { target: GenerationJob['target'] }) {
  const label = TARGET_LABELS[target.type] ?? target.type
  const id = target.id
  if (!id) return <>{label}</>
  const className = 'text-primary underline'
  if (target.type === 'idea') {
    return (
      <Link to="/ideas/$ideaId" params={{ ideaId: id }} className={className}>
        {label}
      </Link>
    )
  }
  if (target.type === 'product') {
    return (
      <Link to="/products/$productId" params={{ productId: id }} className={className}>
        {label}
      </Link>
    )
  }
  if (target.type === 'model') {
    return (
      <Link to="/models/$modelId" params={{ modelId: id }} className={className}>
        {label}
      </Link>
    )
  }
  return <>{label}</>
}

export function JobDetails({ job }: { job: GenerationJob }) {
  const { canGenerate } = useGenAIRoles()
  const { input_assets: rawInputAssets, params, ...words } = job.inputs as {
    input_assets?: unknown[]
    params?: Record<string, unknown>
    [key: string]: unknown
  }
  const inputIds = (rawInputAssets ?? []).filter((id): id is string => typeof id === 'string')
  // A mesh cannot become a product image, so only image results are offered.
  const images = job.status === 'succeeded' ? job.outputs.filter((o) => o.kind === 'image') : []
  const rows: [string, ReactNode][] = [
    ['Capability', CAPABILITY_LABELS[job.capability] ?? job.capability_label],
    ['Status', job.status],
    ['Target', <TargetValue target={job.target} />],
    ['Provider', job.provider],
    ['Model', job.model_ref],
    ['Version', job.model_version === 'official' ? 'Official (maintained by the provider)' : job.model_version],
    ['Version that ran', job.model_version_ran ?? '—'],
    ['Seed', String(job.seed)],
    ['Inputs', Object.entries(words).map(([k, v]) => `${k}: ${String(v)}`).join('\n') || '—'],
    ['Parameters', params ? JSON.stringify(params) : '—'],
    ['Input images', <InputImages ids={inputIds} />],
    ['Estimated cost', usd(job.estimated_cost)],
    ['Cost', job.cost ? `${usd(job.cost)} (${job.cost_provenance})` : '—'],
    ['Requested by', job.requested_by?.name ?? '—'],
    ['Created', when(job.created_at)],
    ['Submitted', when(job.submitted_at)],
    ['Started', when(job.started_at)],
    ['Finished', when(job.completed_at)],
  ]
  if (job.error || job.error_code) rows.push(['Error', failureMessage(job.error_code, job.error)])
  return (
    <>
      <SheetHeader>
        <SheetTitle>How it was made</SheetTitle>
        <SheetDescription>Recorded when the job was created; it never changes.</SheetDescription>
      </SheetHeader>
      <dl className="mt-4 space-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-3 gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="col-span-2 whitespace-pre-wrap break-all">{value}</dd>
          </div>
        ))}
      </dl>
      {images.length > 0 && (
        <section className="mt-6 space-y-2" aria-label="Results">
          <h3 className="text-sm font-medium">Results</h3>
          <div className="grid grid-cols-2 gap-3">
            {images.map((output) => (
              <div key={output.id} className="space-y-2 rounded-md border p-2">
                <div className="relative">
                  <GenAIAssetImage
                    path={output.thumbnail_path ?? output.file_path}
                    alt={`Result ${output.position + 1}`}
                    className="aspect-square w-full"
                  />
                  <AIBadge className="absolute left-1 top-1" />
                </div>
                {canGenerate && <AddToProduct assetId={output.id} />}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  )
}
