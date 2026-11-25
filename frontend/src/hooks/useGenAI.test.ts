/** Generative AI hooks: polling, invalidation and refusals (spec 008, T027/T036). */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor, act } from '@testing-library/react'
import { AxiosError, AxiosHeaders } from 'axios'
import { createElement, type ReactNode } from 'react'

import {
  genaiError,
  invalidateAdoptionTarget,
  useAdoptAsset,
  useEstimate,
  useGenerationJob,
  useUpdateReplicateSettings,
} from './useGenAI'

const api = vi.hoisted(() => ({
  getJob: vi.fn(),
  adopt: vi.fn(),
  estimate: vi.fn(),
  updateSettings: vi.fn(),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: api }))

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
}

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

beforeEach(() => Object.values(api).forEach((fn) => fn.mockReset()))

describe('genaiError', () => {
  it('reads the {code, message} detail', () => {
    const headers = new AxiosHeaders()
    const error = new AxiosError('x', '409', undefined, undefined, {
      status: 409,
      statusText: '',
      headers,
      config: { headers },
      data: { detail: { code: 'budget_exceeded', message: 'Over budget' } },
    })
    expect(genaiError(error)).toEqual({ code: 'budget_exceeded', message: 'Over budget' })
    expect(genaiError(null)).toBeNull()
    expect(genaiError(new Error('x'))?.code).toBe('error')
  })
})

describe('useGenerationJob', () => {
  it('polls while the job runs and stops when it ends', async () => {
    api.getJob
      .mockResolvedValueOnce({ id: 'j', status: 'running' })
      .mockResolvedValue({ id: 'j', status: 'succeeded' })
    const client = newClient()
    const { result } = renderHook(() => useGenerationJob('j'), { wrapper: wrapper(client) })
    await waitFor(() => expect(result.current.job?.status).toBe('running'))
    await waitFor(() => expect(result.current.job?.status).toBe('succeeded'), { timeout: 4000 })
    const calls = api.getJob.mock.calls.length
    await new Promise((r) => setTimeout(r, 2200))
    expect(api.getJob.mock.calls.length).toBe(calls)
  })

  it('does nothing without an id', () => {
    renderHook(() => useGenerationJob(null), { wrapper: wrapper(newClient()) })
    expect(api.getJob).not.toHaveBeenCalled()
  })
})

describe('adoption invalidates its target', () => {
  it.each([
    ['idea', [['ideas']]],
    ['product', [['product-images', 't'], ['product', 't']]],
    ['model', [['model-files', 't'], ['model-file-versions', 't'], ['model', 't']]],
  ] as const)('%s', (type, keys) => {
    const client = newClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    invalidateAdoptionTarget(client, { type, id: 't' })
    expect(spy.mock.calls.map(([arg]) => (arg as { queryKey: unknown }).queryKey)).toEqual(keys)
  })

  it('useAdoptAsset sends the request', async () => {
    api.adopt.mockResolvedValue({ adoption: {} })
    const { result } = renderHook(() => useAdoptAsset(), { wrapper: wrapper(newClient()) })
    await act(() =>
      result.current.mutateAsync({ assetId: 'a', data: { target: { type: 'idea', id: 'i' } } })
    )
    expect(api.adopt).toHaveBeenCalledWith('a', { target: { type: 'idea', id: 'i' } })
  })
})

describe('useEstimate', () => {
  it('waits for the request to settle and keeps money as a string', async () => {
    api.estimate.mockResolvedValue({ estimated_cost: '0.0030', would_exceed_budget: false })
    const request = { capability: 'concept_image' as const, inputs: { prompt: 'x' } }
    const { result } = renderHook(() => useEstimate(request), { wrapper: wrapper(newClient()) })
    await waitFor(() => expect(result.current.estimate?.estimated_cost).toBe('0.0030'))
    expect(api.estimate).toHaveBeenCalledTimes(1)
  })

  it('asks nothing for an incomplete request', async () => {
    renderHook(() => useEstimate(null), { wrapper: wrapper(newClient()) })
    await new Promise((r) => setTimeout(r, 450))
    expect(api.estimate).not.toHaveBeenCalled()
  })
})

describe('useUpdateReplicateSettings', () => {
  it('stores the answer as the settings', async () => {
    api.updateSettings.mockResolvedValue({ is_configured: true })
    const client = newClient()
    const { result } = renderHook(() => useUpdateReplicateSettings(), { wrapper: wrapper(client) })
    await act(() => result.current.mutateAsync({ monthly_budget: '5.00' }))
    expect(api.updateSettings).toHaveBeenCalledWith({ monthly_budget: '5.00' })
    expect(client.getQueryData(['genai', 'settings'])).toEqual({ is_configured: true })
  })
})
