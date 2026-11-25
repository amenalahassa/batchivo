/**
 * Start a generation, follow it and adopt a result (spec 008, US2–US4).
 *
 * The form depends on the capability. The estimated cost (USD, a decimal
 * string) is shown before starting; refusals (not connected, budget,
 * concurrency) are shown as the server words them. Results stay in the job
 * until the operator adopts one explicitly (FR-016).
 */
import { useMemo, useRef, useState, type ReactNode } from 'react'
import { Check, ImagePlus, Loader2, Sparkles } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  genaiError,
  useCancelJob,
  useCapabilities,
  useCreateJob,
  useEstimate,
  useGenerationJob,
  useUploadInput,
} from '@/hooks/useGenAI'
import { cn } from '@/lib/utils'
import type {
  AdoptResponse,
  AssetRef,
  Capability,
  CapabilityInputRule,
  GenAIAsset,
  GenerationJobCreate,
  JobInputs,
  JobTarget,
} from '@/types/genai'
import { AddToProduct } from './AddToProduct'
import { AdoptConfirmDialog } from './AdoptConfirmDialog'
import { AIBadge } from './AIBadge'
import { GenAIAssetImage } from './GenAIAssetImage'
import { JobStatusBadge } from './JobStatusBadge'
import { MeshPreview } from './MeshPreview'
import { CAPABILITY_LABELS, failureMessage, priceText, refusalMessage, usd } from './genaiText'
import { useAdoptWithConfirmation } from './useAdoptWithConfirmation'

/** An image the operator can pick as an input. */
export interface InputCandidate {
  ref: AssetRef
  label: string
  preview?: ReactNode
}

export interface GenerateDialogProps {
  capability: Capability
  /** What the job is for (its history is listed there). */
  target?: JobTarget
  defaultInputs?: JobInputs
  inputAssets?: InputCandidate[]
  /** Where "Adopt" puts a result; no adopt button without it. */
  adoptTarget?: JobTarget
  onAdopted?: (result: AdoptResponse) => void
  /** Opens the dialog; omit it when the dialog is controlled with `open`. */
  trigger?: ReactNode
  title?: string
  /** Controlled mode, e.g. opened from a menu item. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

const SINGLE_INPUT: Capability[] = [
  'image_edit',
  'product_photo_enhance',
  'background_remove',
  'upscale',
  'lifestyle_scene',
]

function needsInputs(capability: Capability) {
  return SINGLE_INPUT.includes(capability) || capability === 'image_to_3d'
}

type InputRules = Record<string, CapabilityInputRule>

/** Capabilities with a "How many" field. */
const COUNTED: Capability[] = ['concept_image', 'lifestyle_scene']

/**
 * How many input images may be picked: what `/capabilities` reports
 * (`inputs.input_assets.max`, then `max_inputs`). Reference images are
 * optional for a concept; with none allowed, no picker is shown.
 */
function maxInputs(capability: Capability, max: number | undefined, rules: InputRules) {
  if (SINGLE_INPUT.includes(capability)) return 1
  const reported = rules.input_assets?.max ?? max
  if (capability === 'image_to_3d') return reported || 4
  return reported ?? 0
}

/**
 * The "How many" bounds. The concept model that takes reference images makes
 * one image per run, so picking a reference caps the count at
 * `inputs.count.max_with_inputs` (1 when the server does not say).
 */
function countBounds(
  capability: Capability,
  rules: InputRules,
  maxCount: number | undefined,
  refs: number
) {
  const min = rules.count?.min ?? 1
  const reported = rules.count?.max ?? maxCount ?? 4
  const max =
    capability === 'concept_image' && refs > 0
      ? (rules.count?.max_with_inputs ?? 1)
      : Math.max(reported, min)
  return {
    min: Math.min(min, max),
    max,
    fallback: rules.count?.default ?? min,
  }
}

export function GenerateDialog(props: GenerateDialogProps) {
  const [ownOpen, setOwnOpen] = useState(false)
  const open = props.open ?? ownOpen
  const setOpen = (next: boolean) => {
    if (props.open === undefined) setOwnOpen(next)
    props.onOpenChange?.(next)
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {props.trigger && <DialogTrigger asChild>{props.trigger}</DialogTrigger>}
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        {open && <GenerateForm {...props} />}
      </DialogContent>
    </Dialog>
  )
}

function GenerateForm({
  capability,
  target,
  defaultInputs,
  inputAssets = [],
  adoptTarget,
  onAdopted,
  title,
}: GenerateDialogProps) {
  const { capabilities, connected, isLoading: capsLoading } = useCapabilities()
  const info = capabilities.find((c) => c.capability === capability)
  const rules: InputRules = info?.inputs ?? {}
  const [inputs, setInputs] = useState<JobInputs>(() => ({
    ...(capability === 'upscale' ? { factor: 2 as const } : {}),
    ...defaultInputs,
  }))
  const [uploaded, setUploaded] = useState<InputCandidate[]>([])
  const candidates = useMemo(() => [...inputAssets, ...uploaded], [inputAssets, uploaded])
  const [selected, setSelected] = useState<string[]>(() =>
    needsInputs(capability) && inputAssets[0] ? [key(inputAssets[0].ref)] : []
  )
  const [jobId, setJobId] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const limit = maxInputs(capability, info?.max_inputs, rules)
  const refs = candidates
    .filter((c) => selected.includes(key(c.ref)))
    .map((c) => c.ref)
    .slice(0, limit)
  const bounds = countBounds(capability, rules, info?.max_count, refs.length)
  const count = COUNTED.includes(capability)
    ? Math.min(Math.max(inputs.count ?? bounds.fallback, bounds.min), bounds.max)
    : undefined
  const request: GenerationJobCreate = {
    capability,
    inputs: {
      ...inputs,
      ...(count !== undefined ? { count } : {}),
      input_assets: refs,
    },
    target: target ?? { type: 'none' },
  }
  const ready = isReady(capability, inputs, refs, rules)
  const { estimate } = useEstimate(ready ? request : null, connected && !jobId)
  const create = useCreateJob()
  const upload = useUploadInput()
  const { job } = useGenerationJob(jobId)
  const cancel = useCancelJob()

  const toggle = (candidate: InputCandidate) => {
    const k = key(candidate.ref)
    setSelected((current) => {
      if (current.includes(k)) return current.filter((x) => x !== k)
      if (limit === 1) return [k]
      return current.length >= limit ? current : [...current, k]
    })
  }

  const onUpload = async (file: File | undefined) => {
    if (!file) return
    const asset = await upload.mutateAsync(file)
    const candidate: InputCandidate = {
      ref: { type: 'asset', id: asset.id },
      label: asset.original_filename || 'Uploaded image',
      preview: (
        <GenAIAssetImage
          path={asset.thumbnail_path ?? asset.file_path}
          alt="Uploaded image"
          className="h-full w-full"
        />
      ),
    }
    setUploaded((current) => [...current, candidate])
    setSelected((current) =>
      limit === 1 ? [key(candidate.ref)] : [...current, key(candidate.ref)].slice(0, limit)
    )
  }

  const start = () => {
    create.mutate(request, { onSuccess: (created) => setJobId(created.id) })
  }

  const heading = title ?? CAPABILITY_LABELS[capability]
  const refusal = refusalMessage(genaiError(create.error))
  const active = job?.status === 'queued' || job?.status === 'running'

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" aria-hidden />
          {heading}
        </DialogTitle>
        <DialogDescription>
          {info ? `${info.model_ref} · ${priceText(info.price)}` : 'Generative AI with Replicate'}
        </DialogDescription>
      </DialogHeader>

      {!capsLoading && !connected && (
        <Alert>
          <AlertDescription>
            Replicate is not connected for this shop. An admin can add a token in{' '}
            <a className="underline" href="/settings?tab=ai">
              Settings → AI
            </a>
            .
          </AlertDescription>
        </Alert>
      )}

      {connected && !job && (
        <div className="space-y-4">
          <CapabilityFields
            capability={capability}
            inputs={inputs}
            onChange={setInputs}
            rules={rules}
            count={count}
            countMin={bounds.min}
            countMax={bounds.max}
          />
          {capability === 'concept_image' && refs.length > 0 && (
            <p className="text-xs text-muted-foreground">
              With reference images, one concept is made per run.
            </p>
          )}

          {(needsInputs(capability) || (capability === 'concept_image' && limit > 0)) && (
            <div className="space-y-2">
              <Label>
                {capability === 'concept_image' ? 'Reference images (optional)' : 'Image'}
                {limit > 1 && <span className="text-muted-foreground"> · up to {limit}</span>}
              </Label>
              <div className="grid grid-cols-4 gap-2">
                {candidates.map((candidate) => {
                  const isOn = selected.includes(key(candidate.ref))
                  return (
                    <button
                      key={key(candidate.ref)}
                      type="button"
                      aria-pressed={isOn}
                      aria-label={candidate.label}
                      onClick={() => toggle(candidate)}
                      className={cn(
                        'relative aspect-square overflow-hidden rounded-md border bg-muted text-xs',
                        isOn && 'ring-2 ring-primary'
                      )}
                    >
                      {candidate.preview ?? <span className="p-1">{candidate.label}</span>}
                      {isOn && (
                        <Check
                          className="absolute right-1 top-1 h-4 w-4 rounded-full bg-primary p-0.5 text-primary-foreground"
                          aria-hidden
                        />
                      )}
                    </button>
                  )
                })}
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="flex aspect-square flex-col items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground"
                  disabled={upload.isPending}
                >
                  {upload.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <ImagePlus className="h-4 w-4" aria-hidden />
                  )}
                  Upload
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  aria-label="Upload an input image"
                  onChange={(e) => onUpload(e.target.files?.[0])}
                />
              </div>
              {upload.error && (
                <p className="text-sm text-destructive">
                  {refusalMessage(genaiError(upload.error))}
                </p>
              )}
            </div>
          )}

          <p className="text-sm text-muted-foreground" data-testid="genai-estimate">
            {estimate
              ? `Estimated cost: ${usd(estimate.estimated_cost)}${
                  estimate.budget
                    ? ` · this month ${usd(estimate.month_to_date)} of ${usd(estimate.budget)}`
                    : ''
                }`
              : 'Estimated cost appears when the form is complete.'}
          </p>
          {estimate?.would_exceed_budget && (
            <p className="text-sm text-destructive">This would go over the monthly AI budget.</p>
          )}
          {refusal && (
            <Alert variant="destructive">
              <AlertDescription>{refusal}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button onClick={start} disabled={!ready || create.isPending}>
              {create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />}
              Generate
            </Button>
          </DialogFooter>
        </div>
      )}

      {job && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <JobStatusBadge status={job.status} />
            <span className="text-xs text-muted-foreground">
              {job.cost ? `Cost ${usd(job.cost)}` : `Estimated ${usd(job.estimated_cost)}`}
            </span>
            {active && job.can_cancel && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => cancel.mutate(job.id)}
                disabled={cancel.isPending}
              >
                Cancel
              </Button>
            )}
          </div>
          {(job.status === 'failed' || job.status === 'canceled') && (
            <Alert variant={job.status === 'failed' ? 'destructive' : 'default'}>
              <AlertDescription>{failureMessage(job.error_code, job.error)}</AlertDescription>
            </Alert>
          )}
          {job.status === 'succeeded' && (
            <div className="grid grid-cols-2 gap-3">
              {job.outputs.map((output) => (
                <ResultCard
                  key={output.id}
                  output={output}
                  adoptTarget={adoptTarget}
                  showsRealItem={job.shows_real_item}
                  onAdopted={onAdopted}
                />
              ))}
            </div>
          )}
          {job.status !== 'succeeded' && !active && (
            <DialogFooter>
              <Button variant="outline" onClick={() => setJobId(null)}>
                Try again
              </Button>
            </DialogFooter>
          )}
        </div>
      )}
    </>
  )
}

function key(ref: AssetRef) {
  return `${ref.type}:${ref.id}`
}

function isReady(capability: Capability, inputs: JobInputs, refs: AssetRef[], rules: InputRules) {
  switch (capability) {
    case 'concept_image':
      return (rules.prompt?.required ?? true) ? Boolean(inputs.prompt?.trim()) : true
    case 'image_edit':
      return Boolean(inputs.instruction?.trim()) && refs.length === 1
    case 'lifestyle_scene':
      return Boolean(inputs.scene?.trim()) && refs.length === 1
    case 'image_to_3d':
      return refs.length >= 1
    default:
      return refs.length === 1
  }
}

interface FieldsProps {
  capability: Capability
  inputs: JobInputs
  onChange: (inputs: JobInputs) => void
  /** Rules from `/capabilities`; each falls back to the value below when absent. */
  rules: InputRules
  count?: number
  countMin: number
  countMax: number
}

function CapabilityFields({
  capability,
  inputs,
  onChange,
  rules,
  count: countValue,
  countMin,
  countMax,
}: FieldsProps) {
  const set = (patch: Partial<JobInputs>) => onChange({ ...inputs, ...patch })
  const maxLength = (field: string, fallback: number) => rules[field]?.max_length ?? fallback
  const count = (
    <div className="space-y-1">
      <Label htmlFor="genai-count">How many</Label>
      <Input
        id="genai-count"
        type="number"
        min={countMin}
        max={countMax}
        value={countValue ?? countMin}
        disabled={countMin === countMax}
        onChange={(e) =>
          set({
            count: Math.min(Math.max(Number(e.target.value) || countMin, countMin), countMax),
          })
        }
        className="w-24"
      />
    </div>
  )
  switch (capability) {
    case 'concept_image':
      return (
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="genai-prompt">Describe the concept</Label>
            <Textarea
              id="genai-prompt"
              value={inputs.prompt ?? ''}
              maxLength={maxLength('prompt', 2000)}
              required={rules.prompt?.required ?? true}
              onChange={(e) => set({ prompt: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="genai-style">Style (optional)</Label>
            <Input
              id="genai-style"
              value={inputs.style ?? ''}
              maxLength={maxLength('style', 200)}
              onChange={(e) => set({ style: e.target.value || undefined })}
            />
          </div>
          {count}
        </div>
      )
    case 'image_edit':
    case 'product_photo_enhance':
      return (
        <div className="space-y-1">
          <Label htmlFor="genai-instruction">
            {capability === 'image_edit' ? 'What to change' : 'Extra instruction (optional)'}
          </Label>
          <Textarea
            id="genai-instruction"
            value={inputs.instruction ?? ''}
            maxLength={maxLength('instruction', capability === 'image_edit' ? 2000 : 500)}
            onChange={(e) => set({ instruction: e.target.value || undefined })}
          />
        </div>
      )
    case 'lifestyle_scene':
      return (
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="genai-scene">Scene</Label>
            <Textarea
              id="genai-scene"
              value={inputs.scene ?? ''}
              maxLength={maxLength('scene', 2000)}
              onChange={(e) => set({ scene: e.target.value })}
            />
          </div>
          {count}
        </div>
      )
    case 'upscale':
      return (
        <div className="space-y-1">
          <Label htmlFor="genai-factor">Factor</Label>
          <select
            id="genai-factor"
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={inputs.factor ?? 2}
            onChange={(e) => set({ factor: Number(e.target.value) === 4 ? 4 : 2 })}
          >
            <option value={2}>2×</option>
            <option value={4}>4×</option>
          </select>
        </div>
      )
    default:
      return null
  }
}

interface ResultCardProps {
  output: GenAIAsset
  adoptTarget?: JobTarget
  showsRealItem: boolean
  onAdopted?: (result: AdoptResponse) => void
}

function ResultCard({ output, adoptTarget, showsRealItem, onAdopted }: ResultCardProps) {
  const adopt = useAdoptWithConfirmation((result) => onAdopted?.(result))
  const done =
    adopt.isSuccess ||
    output.adoptions.some(
      (a) => adoptTarget && a.owner_type === adoptTarget.type && a.owner_id === adoptTarget.id
    )
  const error = adopt.error

  return (
    <div className="space-y-2 rounded-md border p-2">
      <div className="relative">
        {output.kind === 'mesh' ? (
          <MeshPreview path={output.file_path} filename={output.original_filename} />
        ) : (
          <GenAIAssetImage
            path={output.file_path}
            alt={`Result ${output.position + 1}`}
            className="aspect-square w-full"
          />
        )}
        <AIBadge className="absolute left-1 top-1" />
      </div>
      {/* The job's own flag: an edit of a concept or a sketch is not the real item either. */}
      {output.kind === 'image' && !showsRealItem && (
        <p className="text-xs text-muted-foreground">
          Not the real item: a product listing needs a confirmation.
        </p>
      )}
      {adoptTarget && (
        <Button
          size="sm"
          className="w-full"
          disabled={done || adopt.isPending}
          onClick={() => adopt.adopt(output.id, adoptTarget)}
        >
          {done ? 'Added' : `Add to ${adoptTarget.type}`}
        </Button>
      )}
      {/* An image made for an idea or a model may still go to a product; a mesh may not. */}
      {output.kind === 'image' && adoptTarget?.type !== 'product' && (
        <AddToProduct assetId={output.id} />
      )}
      {error && <p className="text-xs text-destructive">{refusalMessage(error)}</p>}
      <AdoptConfirmDialog {...adopt.confirmDialog} />
    </div>
  )
}
