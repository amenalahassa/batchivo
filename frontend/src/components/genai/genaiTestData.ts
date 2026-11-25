/** Builders for the generative AI component tests (spec 008). */
import type { CapabilitiesResponse, GenAIAsset, GenerationJob } from '@/types/genai'

export function anAsset(overrides: Partial<GenAIAsset> = {}): GenAIAsset {
  const id = overrides.id ?? 'asset-1'
  return {
    id,
    job_id: 'job-1',
    source: 'output',
    kind: 'image',
    content_type: 'image/png',
    file_size: 1000,
    width: 64,
    height: 48,
    position: 0,
    original_filename: 'concept_image-1',
    ai_generated: true,
    file_path: `/api/v1/genai/assets/${id}/file`,
    thumbnail_path: `/api/v1/genai/assets/${id}/file?variant=thumb`,
    adoptions: [],
    created_at: '2026-11-24T10:00:00Z',
    ...overrides,
  }
}

export function aJob(overrides: Partial<GenerationJob> = {}): GenerationJob {
  return {
    id: 'job-1',
    capability: 'concept_image',
    capability_label: 'Concept image',
    provider: 'replicate',
    model_ref: 'black-forest-labs/flux-schnell',
    model_version: 'official',
    model_version_ran: 'ab'.repeat(32),
    inputs: { prompt: 'a cable clip', input_assets: [], params: { output_format: 'png' } },
    seed: 7,
    target: { type: 'idea', id: 'idea-1' },
    status: 'queued',
    error: null,
    error_code: null,
    estimated_cost: '0.0030',
    cost: null,
    cost_provenance: null,
    currency: 'USD',
    price: { unit: 'per_output', amount_usd: '0.003', source: 'catalog', assumed: false },
    shows_real_item: false,
    requested_by: { id: 'user-1', name: 'Ada' },
    created_at: '2026-11-24T10:00:00Z',
    submitted_at: null,
    started_at: null,
    completed_at: null,
    outputs: [],
    can_cancel: true,
    ...overrides,
  }
}

export function capabilities(connected = true): CapabilitiesResponse {
  return {
    connected,
    token_source: connected ? 'tenant' : 'none',
    currency: 'USD',
    capabilities: [
      {
        capability: 'concept_image',
        label: 'Concept image',
        output_kind: 'image',
        model_ref: 'black-forest-labs/flux-schnell',
        model_version: 'official',
        pinnable: false,
        overridden: false,
        price: { unit: 'per_output', amount_usd: '0.003', source: 'catalog', assumed: false },
        max_count: 4,
        max_inputs: 4,
        inputs: {
          prompt: { required: true, max_length: 2000 },
          input_assets: { required: false, min: 0, max: 4 },
          count: { min: 1, max: 4, default: 1, max_with_inputs: 1 },
          style: { max_length: 200 },
        },
        time_limit_s: 600,
        shows_real_item: false,
      },
      {
        capability: 'background_remove',
        label: 'Remove background',
        output_kind: 'image',
        model_ref: '851-labs/background-remover',
        model_version: 'a'.repeat(64),
        pinnable: true,
        overridden: false,
        price: { unit: 'per_second', amount_usd: '0.000225', source: 'catalog', assumed: false },
        max_count: 1,
        max_inputs: 1,
        time_limit_s: 600,
        shows_real_item: true,
      },
    ],
  }
}
