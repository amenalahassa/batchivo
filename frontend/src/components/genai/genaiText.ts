/**
 * Words for the generative AI screens (spec 008): labels, statuses, refusals, money.
 */
import type { Capability, GenAIErrorDetail, JobStatus, PriceInfo } from '@/types/genai'

export const CAPABILITY_LABELS: Record<Capability, string> = {
  concept_image: 'Concept image',
  image_edit: 'Edit with AI',
  product_photo_enhance: 'Enhance photo',
  background_remove: 'Remove background',
  upscale: 'Upscale',
  lifestyle_scene: 'Lifestyle scene',
  image_to_3d: 'Draft 3D shape',
}

export const STATUS_LABELS: Record<JobStatus, string> = {
  queued: 'Queued',
  running: 'Generating…',
  succeeded: 'Done',
  failed: 'Failed',
  canceled: 'Canceled',
}

const REFUSALS: Record<string, string> = {
  not_connected: 'Replicate is not connected. An admin can add a token in Settings → AI.',
  concurrency_limit: 'Too many generations are running. Try again when one finishes.',
  queue_unavailable: 'The job could not be queued. Try again in a moment.',
  needs_confirmation: 'Listings must show the real item.',
  already_adopted: 'This result was already added here.',
  not_succeeded: 'This generation has not finished.',
  timeout: 'The generation took too long and was stopped.',
  auth: 'Replicate refused the token. Check it in Settings → AI.',
  rate_limited: 'Replicate is busy. Try again in a moment.',
  download_failed: 'The result could not be saved.',
}

/** A refusal as the operator reads it; the server's own message wins when it has one. */
export function refusalMessage(error: GenAIErrorDetail | null | undefined): string | null {
  if (!error) return null
  return error.message || REFUSALS[error.code] || 'Something went wrong. Try again.'
}

/** A job failure reason as shown on a job. */
export function failureMessage(code: string | null, error: string | null): string {
  if (error) return error
  return (code && REFUSALS[code]) || 'The generation failed.'
}

/** A USD amount (decimal string) for display: never converted to a JS number. */
export function usd(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  return `$${amount} USD`
}

const UNITS: Record<string, string> = {
  per_output: 'per image',
  per_run: 'per run',
  per_second: 'per second of compute',
}

export function priceText(price: PriceInfo): string {
  const text = `$${price.amount_usd} ${UNITS[price.unit] ?? price.unit}`
  return price.assumed ? `${text} (approximate)` : text
}
