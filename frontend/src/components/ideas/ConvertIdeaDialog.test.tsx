/** Converting an idea, and who may (spec 007, FR-002, FR-023 to FR-030, T045). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'

import { render, screen, waitFor } from '@/test/test-utils'

import { ConvertIdeaDialog, PRODUCT_ROLE_REASON } from './ConvertIdeaDialog'
import { IdeaHeader } from './IdeaHeader'
import { anIdea } from './ideaTestData'

const api = vi.hoisted(() => ({
  convert: vi.fn(),
  update: vi.fn(),
  getImageBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/ideas', () => ({ ideasApi: api }))
vi.mock('@/lib/api/sku', () => ({
  skuApi: {
    getNextSKU: vi.fn(async (type: string) => ({
      next_sku: type === 'MOD' ? 'MOD-007' : 'PROD-012',
      highest_existing: 1,
    })),
  },
}))

beforeEach(() => {
  api.convert.mockReset()
  api.update.mockReset()
})

describe('ConvertIdeaDialog', () => {
  it('prefills the name and the next model reference, and converts to a model', async () => {
    api.convert.mockResolvedValue({
      idea: anIdea(),
      model_id: 'model-1',
      product_id: null,
      copied_images: 0,
      warnings: [],
    })
    render(<ConvertIdeaDialog idea={anIdea()} target="model" onClose={vi.fn()} />)
    expect(screen.getByLabelText('Name')).toHaveValue('Sun visor clip')
    await waitFor(() => expect(screen.getByLabelText('Model reference')).toHaveValue('MOD-007'))
    expect(screen.queryByLabelText('Product reference')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Convert' }))
    expect(api.convert).toHaveBeenCalledWith('idea-1', {
      target: 'model',
      name: 'Sun visor clip',
      model_sku: 'MOD-007',
      product_sku: undefined,
      include_images: true,
    })
    expect(await screen.findByRole('link', { name: 'Open the model' })).toBeInTheDocument()
  })

  it('converts to a product reusing the linked model, without copying images when asked', async () => {
    api.convert.mockResolvedValue({
      idea: anIdea(),
      model_id: 'model-1',
      product_id: 'product-1',
      copied_images: 0,
      warnings: ['An image file was missing and was not copied'],
    })
    const idea = anIdea({ model: { id: 'model-1', name: 'Clip', sku: 'MOD-001', state: 'linked' } })
    render(<ConvertIdeaDialog idea={idea} target="product" onClose={vi.fn()} />)
    expect(screen.queryByLabelText('Model reference')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Product reference')).toHaveValue('PROD-012'))
    await userEvent.click(screen.getByLabelText('Copy the cover and pinned images'))
    await userEvent.click(screen.getByRole('button', { name: 'Convert' }))
    expect(api.convert).toHaveBeenCalledWith(
      'idea-1',
      expect.objectContaining({ target: 'product', model_sku: undefined, include_images: false })
    )
    expect(await screen.findByRole('link', { name: 'Open the product' })).toBeInTheDocument()
    expect(screen.getByLabelText('Warnings')).toHaveTextContent('missing')
  })

  it('shows why the server refused', async () => {
    api.convert.mockRejectedValue(
      new AxiosError('409', 'ERR_BAD_REQUEST', undefined, undefined, {
        status: 409,
        statusText: 'Conflict',
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: 'This idea was already converted to a product' },
      })
    )
    render(<ConvertIdeaDialog idea={anIdea()} target="model" onClose={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Convert' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already converted to a product')
  })
})

describe('IdeaHeader', () => {
  it('lets a member convert to a model but not to a product, saying why', () => {
    render(<IdeaHeader idea={anIdea()} canWrite canCreateProduct={false} />)
    expect(screen.getByRole('button', { name: 'Convert to model' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Convert to product' })).toBeDisabled()
    expect(screen.getByText(PRODUCT_ROLE_REASON)).toBeInTheDocument()
  })

  it('lets an admin convert to a product', () => {
    render(<IdeaHeader idea={anIdea()} canWrite canCreateProduct />)
    expect(screen.getByRole('button', { name: 'Convert to product' })).toBeEnabled()
    expect(screen.queryByText(PRODUCT_ROLE_REASON)).not.toBeInTheDocument()
  })

  it('offers no second conversion to a product, and links to it', () => {
    const idea = anIdea({
      status: 'converted',
      model: { id: 'm', name: 'Clip', sku: 'MOD-001', state: 'linked' },
      product: { id: 'p', name: 'Clip set', sku: 'PROD-001', state: 'linked' },
    })
    render(<IdeaHeader idea={idea} canWrite canCreateProduct />)
    expect(screen.queryByRole('button', { name: /Convert to/ })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Clip set/ })).toBeInTheDocument()
  })

  it('says the idea was already converted to a product, with its link', () => {
    const idea = anIdea({
      status: 'converted',
      product: { id: 'p', name: 'Clip set', sku: 'PROD-001', state: 'linked' },
    })
    render(<IdeaHeader idea={idea} canWrite canCreateProduct />)
    expect(screen.getByRole('status')).toHaveTextContent('Already converted to a product')
    expect(screen.getByRole('link', { name: 'open it' })).toHaveAttribute(
      'href',
      '/products/$productId'
    )
  })

  it('keeps the report score as history once the five scores are set', () => {
    const idea = anIdea({ score: 17, score_source: 'scores', report_score: 20 })
    render(<IdeaHeader idea={idea} canWrite={false} canCreateProduct={false} />)
    expect(screen.getByText('17/25')).toBeInTheDocument()
    expect(screen.getByText('(report score 20/25)')).toBeInTheDocument()
  })

  it('shows no separate report score while it is the score', () => {
    const idea = anIdea({ score: 20, score_source: 'report', report_score: 20 })
    render(<IdeaHeader idea={idea} canWrite={false} canCreateProduct={false} />)
    expect(screen.getByText('Report score 20/25')).toBeInTheDocument()
    expect(screen.queryByText('(report score 20/25)')).not.toBeInTheDocument()
  })

  it('shows a deleted model as gone', () => {
    const idea = anIdea({ model: { id: null, name: null, sku: null, state: 'gone' } })
    render(<IdeaHeader idea={idea} canWrite canCreateProduct />)
    expect(screen.getByText('no longer exists')).toBeInTheDocument()
  })

  it('gives a viewer nothing to change', () => {
    render(<IdeaHeader idea={anIdea()} canWrite={false} canCreateProduct={false} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Inbox')).toBeInTheDocument()
  })

  it('archives the idea and changes its status', async () => {
    api.update.mockResolvedValue(anIdea())
    render(<IdeaHeader idea={anIdea()} canWrite canCreateProduct />)
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'validating')
    await userEvent.click(screen.getByRole('button', { name: 'Archive' }))
    expect(api.update).toHaveBeenCalledWith('idea-1', { status: 'validating' })
    expect(api.update).toHaveBeenCalledWith('idea-1', { archived: true })
  })
})
