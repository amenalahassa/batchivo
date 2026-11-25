/** Jobs of a target, how each was made, and cancel (spec 008, US5, T046). */
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { AxiosError, AxiosHeaders } from 'axios'

import { render, screen, waitFor, within } from '@/test/test-utils'

import { JobHistory } from './JobHistory'
import { aJob, anAsset } from './genaiTestData'

const api = vi.hoisted(() => ({
  listJobs: vi.fn(),
  cancelJob: vi.fn(),
  adopt: vi.fn(),
  getBlob: vi.fn(),
  assetFilePath: (id: string, variant: 'full' | 'thumb' = 'full') =>
    `/api/v1/genai/assets/${id}/file${variant === 'thumb' ? '?variant=thumb' : ''}`,
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: api }))
const products = vi.hoisted(() => ({ listProducts: vi.fn() }))
vi.mock('@/lib/api/products', () => products)
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    to,
    params,
    children,
  }: {
    to: string
    params: Record<string, string>
    children: ReactNode
  }) => <a href={to.replace(/\$(\w+)/g, (_, key: string) => params[key])}>{children}</a>,
}))

function needsConfirmation() {
  const headers = new AxiosHeaders()
  return new AxiosError('refused', '409', undefined, undefined, {
    status: 409,
    statusText: '',
    headers,
    config: { headers },
    data: { detail: { code: 'needs_confirmation', message: 'Listings must show the real item.' } },
  })
}
const roles = vi.hoisted(() => ({ value: { canGenerate: true, canManageSettings: false } }))
vi.mock('./useGenAIRoles', () => ({ useGenAIRoles: () => roles.value }))

const jobs = [
  aJob({ id: 'run', status: 'running' }),
  aJob({
    id: 'done',
    status: 'succeeded',
    can_cancel: false,
    cost: '0.0420',
    cost_provenance: 'estimated',
    capability: 'image_to_3d',
    model_ref: 'firtoz/trellis',
    model_version: 'e8'.repeat(32),
  }),
  aJob({
    id: 'bad',
    status: 'failed',
    can_cancel: false,
    error: 'NSFW content',
    error_code: 'provider_error',
    cost: '0',
    cost_provenance: 'computed',
  }),
]

beforeEach(() => {
  api.adopt.mockReset()
  api.getBlob.mockReset().mockImplementation(() => new Promise(() => {}))
  products.listProducts.mockReset().mockResolvedValue({
    products: [
      { id: 'product-1', name: 'Cable clip', sku: 'CLIP-1' },
      { id: 'product-2', name: 'Desk hook', sku: 'HOOK-1' },
    ],
    total: 2,
    skip: 0,
    limit: 10,
  })
  api.listJobs.mockReset().mockResolvedValue({ items: jobs, total: 3 })
  api.cancelJob.mockReset().mockResolvedValue(aJob({ id: 'run', status: 'canceled' }))
  roles.value = { canGenerate: true, canManageSettings: false }
})

describe('JobHistory', () => {
  it('lists jobs of the target with status, cost provenance and failure', async () => {
    render(<JobHistory targetType="idea" targetId="idea-1" />)
    const list = await screen.findByRole('list', { name: 'AI generations' })
    expect(api.listJobs).toHaveBeenCalledWith({ target_type: 'idea', target_id: 'idea-1', limit: 50 })
    expect(within(list).getAllByRole('listitem')).toHaveLength(3)
    expect(within(list).getByText('≈ $0.0420 USD (estimated)')).toBeInTheDocument()
    expect(within(list).getByText('NSFW content')).toBeInTheDocument()
  })

  it('cancels a running job for a member', async () => {
    render(<JobHistory targetType="idea" targetId="idea-1" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(api.cancelJob).toHaveBeenCalledWith('run')
  })

  it('hides cancel from a viewer', async () => {
    roles.value = { canGenerate: false, canManageSettings: false }
    render(<JobHistory targetType="idea" targetId="idea-1" />)
    await screen.findByRole('list', { name: 'AI generations' })
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it('shows how a job was made', async () => {
    render(<JobHistory targetType="model" targetId="model-1" />)
    const buttons = await screen.findAllByRole('button', { name: 'How it was made' })
    await userEvent.click(buttons[1])
    expect(await screen.findByText('firtoz/trellis')).toBeInTheDocument()
    expect(screen.getByText('e8'.repeat(32))).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('shows the provider, target and submission time', async () => {
    const submittedAt = '2026-11-20T10:15:00Z'
    api.listJobs.mockResolvedValue({
      items: [
        aJob({
          id: 'sent',
          provider: 'replicate',
          target: { type: 'product', id: 'product-9' },
          submitted_at: submittedAt,
        }),
      ],
      total: 1,
    })
    render(<JobHistory targetType="product" targetId="product-9" />)
    await userEvent.click(await screen.findByRole('button', { name: 'How it was made' }))
    const row = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling
    expect(await screen.findByText('replicate')).toBeInTheDocument()
    expect(row('Provider')).toHaveTextContent('replicate')
    expect(within(row('Target') as HTMLElement).getByRole('link', { name: 'Product' })).toHaveAttribute(
      'href',
      '/products/product-9'
    )
    expect(row('Submitted')).toHaveTextContent(new Date(submittedAt).toLocaleString())
  })

  it('shows a job without a target or submission as such', async () => {
    api.listJobs.mockResolvedValue({
      items: [aJob({ id: 'loose', target: { type: 'none', id: null }, submitted_at: null })],
      total: 1,
    })
    render(<JobHistory targetType="idea" targetId="idea-1" />)
    await userEvent.click(await screen.findByRole('button', { name: 'How it was made' }))
    const row = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling
    await screen.findByText('How it was made', { selector: 'h2' })
    expect(row('Target')).toHaveTextContent('None')
    expect(within(row('Target') as HTMLElement).queryByRole('link')).not.toBeInTheDocument()
    expect(row('Submitted')).toHaveTextContent('—')
  })

  it('says when there is nothing yet', async () => {
    api.listJobs.mockResolvedValue({ items: [], total: 0 })
    render(<JobHistory targetType="product" targetId="p-1" />)
    expect(await screen.findByText('No AI generations yet.')).toBeInTheDocument()
  })

  describe('input images and results in "How it was made"', () => {
    const concept = aJob({
      id: 'concept',
      status: 'succeeded',
      can_cancel: false,
      inputs: { prompt: 'a cable clip', input_assets: ['in-1', 'in-2'] },
      outputs: [anAsset({ id: 'out-1' })],
    })
    const draft = aJob({
      id: 'draft',
      status: 'succeeded',
      can_cancel: false,
      capability: 'image_to_3d',
      target: { type: 'model', id: 'model-1' },
      outputs: [anAsset({ id: 'mesh-1', kind: 'mesh', content_type: 'model/gltf-binary' })],
    })

    async function openDetails(job = concept) {
      api.listJobs.mockResolvedValue({ items: [job], total: 1 })
      render(<JobHistory targetType="idea" targetId="idea-1" />)
      await userEvent.click(await screen.findByRole('button', { name: 'How it was made' }))
    }

    it('shows a thumbnail of each input image', async () => {
      await openDetails()
      const inputs = await screen.findByRole('list', { name: 'Input images' })
      expect(within(inputs).getAllByRole('listitem')).toHaveLength(2)
      await waitFor(() =>
        expect(api.getBlob).toHaveBeenCalledWith('/api/v1/genai/assets/in-1/file?variant=thumb')
      )
      expect(api.getBlob).toHaveBeenCalledWith('/api/v1/genai/assets/in-2/file?variant=thumb')
    })

    it('says so when a job had no input image', async () => {
      await openDetails(aJob({ id: 'plain', inputs: { prompt: 'x', input_assets: [] } }))
      expect(await screen.findByText('Input images')).toBeInTheDocument()
      expect(screen.queryByRole('list', { name: 'Input images' })).not.toBeInTheDocument()
    })

    it('adds an image result to the product picked', async () => {
      api.adopt.mockResolvedValue({ adoption: {}, product_image_id: 'pi-1' })
      await openDetails()
      await userEvent.click(await screen.findByRole('button', { name: 'Add to product…' }))
      await userEvent.type(screen.getByRole('textbox', { name: 'Search products' }), 'hook')
      await waitFor(() =>
        expect(products.listProducts).toHaveBeenLastCalledWith({ search: 'hook', limit: 10 })
      )
      await userEvent.click(await screen.findByRole('button', { name: /Desk hook/ }))
      expect(api.adopt).toHaveBeenCalledWith('out-1', {
        target: { type: 'product', id: 'product-2' },
        confirm_not_real_item: false,
      })
      expect(await screen.findByText('Added to Desk hook')).toBeInTheDocument()
    })

    it('asks before adding an imagined picture, and re-sends with the confirmation', async () => {
      api.adopt
        .mockRejectedValueOnce(needsConfirmation())
        .mockResolvedValueOnce({ adoption: {}, product_image_id: 'pi-1' })
      await openDetails()
      await userEvent.click(await screen.findByRole('button', { name: 'Add to product…' }))
      await userEvent.click(await screen.findByRole('button', { name: /Cable clip/ }))
      expect(await screen.findByText('Listings must show the real item')).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Add anyway' }))
      await waitFor(() =>
        expect(api.adopt).toHaveBeenLastCalledWith('out-1', {
          target: { type: 'product', id: 'product-1' },
          confirm_not_real_item: true,
        })
      )
      expect(api.adopt).toHaveBeenCalledTimes(2)
      expect(await screen.findByText('Added to Cable clip')).toBeInTheDocument()
    })

    it('adds nothing when the confirmation is cancelled', async () => {
      api.adopt.mockRejectedValueOnce(needsConfirmation())
      await openDetails()
      await userEvent.click(await screen.findByRole('button', { name: 'Add to product…' }))
      await userEvent.click(await screen.findByRole('button', { name: /Cable clip/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
      expect(api.adopt).toHaveBeenCalledTimes(1)
      expect(screen.queryByText('Added to Cable clip')).not.toBeInTheDocument()
    })

    it('does not offer a mesh as a product image', async () => {
      await openDetails(draft)
      await screen.findByText('How it was made', { selector: 'h2' })
      expect(screen.queryByRole('button', { name: 'Add to product…' })).not.toBeInTheDocument()
    })

    it('does not offer adoption to a viewer', async () => {
      roles.value = { canGenerate: false, canManageSettings: false }
      await openDetails()
      await screen.findByRole('region', { name: 'Results' })
      expect(screen.queryByRole('button', { name: 'Add to product…' })).not.toBeInTheDocument()
    })
  })
})
