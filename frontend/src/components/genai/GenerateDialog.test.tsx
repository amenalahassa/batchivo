/** Starting, following and adopting a generation (spec 008, US2–US4, T038). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'

import { Button } from '@/components/ui/button'
import { render, screen, waitFor } from '@/test/test-utils'

import { GenerateDialog } from './GenerateDialog'
import { aJob, anAsset, capabilities } from './genaiTestData'

const api = vi.hoisted(() => ({
  capabilities: vi.fn(),
  estimate: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  adopt: vi.fn(),
  upload: vi.fn(),
  getBlob: vi.fn(() => new Promise(() => {})),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: api }))
const products = vi.hoisted(() => ({ listProducts: vi.fn() }))
vi.mock('@/lib/api/products', () => products)

function refused(status: number, code: string, message: string) {
  const headers = new AxiosHeaders()
  return new AxiosError('refused', String(status), undefined, undefined, {
    status,
    statusText: '',
    headers,
    config: { headers },
    data: { detail: { code, message } },
  })
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  api.getBlob.mockImplementation(() => new Promise(() => {}))
  api.capabilities.mockResolvedValue(capabilities())
  api.estimate.mockResolvedValue({
    estimated_cost: '0.0030',
    month_to_date: '1.2000',
    budget: '10.00',
    would_exceed_budget: false,
    currency: 'USD',
  })
})

async function open(props: Partial<Parameters<typeof GenerateDialog>[0]> = {}) {
  render(
    <GenerateDialog
      capability="concept_image"
      target={{ type: 'idea', id: 'idea-1' }}
      adoptTarget={{ type: 'idea', id: 'idea-1' }}
      trigger={<Button>Generate concept</Button>}
      {...props}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: 'Generate concept' }))
}

describe('GenerateDialog', () => {
  it('tells a shop without a token where to connect', async () => {
    api.capabilities.mockResolvedValue(capabilities(false))
    await open()
    expect(await screen.findByText(/Replicate is not connected/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Settings → AI' })).toHaveAttribute(
      'href',
      '/settings?tab=ai'
    )
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument()
  })

  it('shows the estimate in USD, starts the job and adopts a result', async () => {
    await open({ defaultInputs: { prompt: 'A clip' } })
    expect(await screen.findByLabelText('Describe the concept')).toHaveValue('A clip')
    expect(await screen.findByText(/Estimated cost: \$0\.0030 USD/)).toBeInTheDocument()
    expect(screen.getByText(/this month \$1\.2000 USD of \$10\.00 USD/)).toBeInTheDocument()

    const done = aJob({
      status: 'succeeded',
      cost: '0.0030',
      cost_provenance: 'computed',
      can_cancel: false,
      outputs: [anAsset()],
    })
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(done)
    api.adopt.mockResolvedValue({ adoption: {}, idea_entry_id: 'entry-1' })
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }))
    expect(api.createJob).toHaveBeenCalledWith({
      capability: 'concept_image',
      inputs: { count: 1, prompt: 'A clip', input_assets: [] },
      target: { type: 'idea', id: 'idea-1' },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add to idea' }))
    expect(api.adopt).toHaveBeenCalledWith('asset-1', {
      target: { type: 'idea', id: 'idea-1' },
      confirm_not_real_item: false,
    })
    expect(await screen.findByRole('button', { name: 'Added' })).toBeDisabled()
  })

  it('shows the budget refusal as the server words it', async () => {
    api.createJob.mockRejectedValue(
      refused(409, 'budget_exceeded', 'This generation would go over the monthly budget of $1.00.')
    )
    await open({ defaultInputs: { prompt: 'A clip' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByText(/over the monthly budget of \$1\.00/)).toBeInTheDocument()
  })

  it('needs an input image for a photo capability, and sends the picked one', async () => {
    api.createJob.mockResolvedValue(aJob({ capability: 'background_remove' }))
    api.getJob.mockResolvedValue(aJob({ capability: 'background_remove', status: 'running' }))
    await open({
      capability: 'background_remove',
      title: 'Remove background',
      trigger: <Button>Generate concept</Button>,
      inputAssets: [{ ref: { type: 'product_image', id: 'img-1' }, label: 'Front photo' }],
    })
    const photo = await screen.findByRole('button', { name: 'Front photo' })
    expect(photo).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }))
    expect(api.createJob.mock.calls[0][0].inputs.input_assets).toEqual([
      { type: 'product_image', id: 'img-1' },
    ])
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(api.cancelJob).toHaveBeenCalledWith('job-1')
  })

  it('asks for confirmation before adding an imagined picture to a product', async () => {
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(
      aJob({ status: 'succeeded', can_cancel: false, outputs: [anAsset()] })
    )
    api.adopt
      .mockRejectedValueOnce(refused(409, 'needs_confirmation', 'Listings must show the real item.'))
      .mockResolvedValueOnce({ adoption: {}, product_image_id: 'pi-1' })
    await open({
      adoptTarget: { type: 'product', id: 'product-1' },
      defaultInputs: { prompt: 'A clip' },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Add to product' }))
    expect(await screen.findByText('Listings must show the real item')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add anyway' }))
    await waitFor(() =>
      expect(api.adopt).toHaveBeenLastCalledWith('asset-1', {
        target: { type: 'product', id: 'product-1' },
        confirm_not_real_item: true,
      })
    )
  })

  it("marks a result as not the real item from the job's own flag", async () => {
    // An edit of a concept: the capability shows the real item, the job does not.
    const edit = { capability: 'image_edit' as const, status: 'succeeded' as const }
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(
      aJob({ ...edit, shows_real_item: false, can_cancel: false, outputs: [anAsset()] })
    )
    await open({ defaultInputs: { prompt: 'A clip' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByText(/Not the real item/)).toBeInTheDocument()
  })

  it('does not mark a result that shows the real item', async () => {
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(
      aJob({ status: 'succeeded', shows_real_item: true, can_cancel: false, outputs: [anAsset()] })
    )
    await open({ defaultInputs: { prompt: 'A clip' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByRole('button', { name: 'Add to idea' })).toBeInTheDocument()
    expect(screen.queryByText(/Not the real item/)).not.toBeInTheDocument()
  })

  it('shows why a job failed', async () => {
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(
      aJob({ status: 'failed', error: 'NSFW content', error_code: 'provider_error', can_cancel: false })
    )
    await open({ defaultInputs: { prompt: 'A clip' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByText('NSFW content')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('uploads an input image and selects it', async () => {
    api.upload.mockResolvedValue(anAsset({ id: 'up-1', source: 'upload', original_filename: 'mine.png' }))
    await open({ capability: 'background_remove', title: 'Remove background' })
    const input = await screen.findByLabelText('Upload an input image')
    await userEvent.upload(input, new File(['x'], 'mine.png', { type: 'image/png' }))
    expect(await screen.findByRole('button', { name: 'mine.png' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
  })

  it('lets a concept pick reference images and sends them, one image per run', async () => {
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(aJob({ status: 'running' }))
    await open({
      defaultInputs: { prompt: 'A clip', count: 3 },
      inputAssets: [
        { ref: { type: 'idea_entry', id: 'entry-1' }, label: 'Sketch' },
        { ref: { type: 'idea_entry', id: 'entry-2' }, label: 'Photo' },
      ],
    })
    expect(await screen.findByText(/Reference images \(optional\)/)).toBeInTheDocument()
    expect(screen.getByText(/up to 4/)).toBeInTheDocument()
    const sketch = screen.getByRole('button', { name: 'Sketch' })
    // Optional: nothing is picked up front.
    expect(sketch).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByLabelText('How many')).toHaveValue(3)

    await userEvent.click(sketch)
    expect(sketch).toHaveAttribute('aria-pressed', 'true')
    // The concept model with references makes one image per run.
    expect(screen.getByLabelText('How many')).toHaveValue(1)
    expect(screen.getByText(/one concept is made per run/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Generate' }))
    expect(api.createJob).toHaveBeenCalledWith({
      capability: 'concept_image',
      inputs: {
        prompt: 'A clip',
        count: 1,
        input_assets: [{ type: 'idea_entry', id: 'entry-1' }],
      },
      target: { type: 'idea', id: 'idea-1' },
    })
  })

  it('hides the reference picker when the server allows no reference image', async () => {
    const caps = capabilities()
    caps.capabilities[0] = { ...caps.capabilities[0], max_inputs: 0, inputs: undefined }
    api.capabilities.mockResolvedValue(caps)
    await open({
      defaultInputs: { prompt: 'A clip' },
      inputAssets: [{ ref: { type: 'idea_entry', id: 'entry-1' }, label: 'Sketch' }],
    })
    expect(await screen.findByLabelText('Describe the concept')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sketch' })).not.toBeInTheDocument()
  })

  it('follows the input rules /capabilities reports', async () => {
    const caps = capabilities()
    caps.capabilities[0] = {
      ...caps.capabilities[0],
      inputs: {
        prompt: { required: true, max_length: 300 },
        style: { max_length: 50 },
        count: { min: 2, max: 3, default: 2 },
      },
    }
    api.capabilities.mockResolvedValue(caps)
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(aJob({ status: 'running' }))
    await open()
    const prompt = await screen.findByLabelText('Describe the concept')
    expect(prompt).toHaveAttribute('maxLength', '300')
    expect(prompt).toBeRequired()
    expect(screen.getByLabelText('Style (optional)')).toHaveAttribute('maxLength', '50')
    const count = screen.getByLabelText('How many')
    expect(count).toHaveValue(2)
    expect(count).toHaveAttribute('min', '2')
    expect(count).toHaveAttribute('max', '3')
    // Required prompt: nothing starts without it.
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled()
    await userEvent.type(prompt, 'A clip')
    await userEvent.click(screen.getByRole('button', { name: 'Generate' }))
    expect(api.createJob.mock.calls[0][0].inputs.count).toBe(2)
  })

  it('falls back to the built-in rules when /capabilities has no inputs', async () => {
    const caps = capabilities()
    caps.capabilities[0] = { ...caps.capabilities[0], inputs: undefined, max_count: 4 }
    api.capabilities.mockResolvedValue(caps)
    await open()
    expect(await screen.findByLabelText('Describe the concept')).toHaveAttribute('maxLength', '2000')
    expect(screen.getByLabelText('Style (optional)')).toHaveAttribute('maxLength', '200')
    expect(screen.getByLabelText('How many')).toHaveAttribute('max', '4')
    expect(screen.getByLabelText('How many')).toHaveValue(1)
  })

  it('adds an idea result to a chosen product', async () => {
    products.listProducts.mockResolvedValue({
      products: [{ id: 'product-9', name: 'Cable clip', sku: 'CLIP-1' }],
      total: 1,
      skip: 0,
      limit: 10,
    })
    api.createJob.mockResolvedValue(aJob())
    api.getJob.mockResolvedValue(
      aJob({ status: 'succeeded', can_cancel: false, outputs: [anAsset()] })
    )
    api.adopt.mockResolvedValue({ adoption: {}, product_image_id: 'pi-1' })
    await open({ defaultInputs: { prompt: 'A clip' } })
    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Add to product…' }))
    await userEvent.click(await screen.findByRole('button', { name: /Cable clip/ }))
    expect(api.adopt).toHaveBeenCalledWith('asset-1', {
      target: { type: 'product', id: 'product-9' },
      confirm_not_real_item: false,
    })
    expect(await screen.findByText('Added to Cable clip')).toBeInTheDocument()
  })
})
