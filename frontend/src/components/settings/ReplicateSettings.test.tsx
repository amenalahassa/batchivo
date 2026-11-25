/** The AI settings panel (spec 008, T028). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'

import { render, screen, waitFor, within } from '@/test/test-utils'
import type {
  CapabilitiesResponse,
  ReplicateSettings as ReplicateSettingsData,
} from '@/types/genai'

import { ReplicateSettings } from './ReplicateSettings'

const api = vi.hoisted(() => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  testConnection: vi.fn(),
  usage: vi.fn(),
  capabilities: vi.fn(),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: api }))

const FULL_TOKEN = 'r8_SECRETSECRETSECRETab12'
const VERSION = 'a'.repeat(64)

function aSettings(overrides: Partial<ReplicateSettingsData> = {}): ReplicateSettingsData {
  return {
    is_configured: true,
    token_masked: '…ab12',
    token_source: 'tenant',
    platform_token_available: true,
    platform_token_allowed: false,
    monthly_budget: '25.00',
    currency: 'USD',
    month_to_date: '3.4100',
    jobs_this_month: 12,
    active_jobs: 1,
    concurrency_limit: 3,
    model_overrides: {},
    updated_at: null,
    ...overrides,
  }
}

const capabilities: CapabilitiesResponse = {
  connected: true,
  token_source: 'tenant',
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
      price: {
        unit: 'per_output',
        amount_usd: '0.003',
        source: 'catalog',
        assumed: false,
      },
      max_count: 4,
      max_inputs: 0,
      time_limit_s: 120,
      shows_real_item: false,
    },
    {
      capability: 'image_edit',
      label: 'Image edit',
      output_kind: 'image',
      model_ref: 'owner/editor',
      model_version: VERSION,
      pinnable: true,
      overridden: true,
      price: {
        unit: 'per_output',
        amount_usd: '0.04',
        source: 'override',
        assumed: false,
      },
      max_count: 1,
      max_inputs: 1,
      time_limit_s: 120,
      shows_real_item: true,
    },
  ],
}

function refusal(message: string) {
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 422,
    statusText: 'Unprocessable',
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: { detail: { code: 'invalid_input', message } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getSettings.mockResolvedValue(aSettings())
  api.updateSettings.mockImplementation(async () => aSettings())
  api.usage.mockResolvedValue({
    currency: 'USD',
    months: [
      { month: '2026-11', cost: '3.4100', jobs: 12 },
      { month: '2026-10', cost: '0.1200', jobs: 2 },
    ],
  })
  api.capabilities.mockResolvedValue(capabilities)
})

async function renderPanel() {
  const result = render(<ReplicateSettings />)
  await screen.findByText('Replicate connection')
  return result
}

describe('ReplicateSettings token', () => {
  it('shows the masked token and never the full one', async () => {
    const { container } = await renderPanel()
    expect(screen.getByText('…ab12')).toBeInTheDocument()
    expect(screen.getByText('Your own token')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Your Replicate token'), FULL_TOKEN)
    expect(screen.getByLabelText('Your Replicate token')).toHaveAttribute('type', 'password')
    expect(container.textContent).not.toContain(FULL_TOKEN)
  })

  it('says which token is in use and whether the platform one is available', async () => {
    api.getSettings.mockResolvedValue(
      aSettings({
        is_configured: false,
        token_masked: null,
        token_source: 'platform',
        platform_token_allowed: true,
      })
    )
    await renderPanel()
    expect(screen.getByText('Platform token, provided by Batchivo')).toBeInTheDocument()
    expect(screen.getByText(/platform token is available to this shop/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove token' })).not.toBeInTheDocument()
  })

  it('says not connected and no platform token', async () => {
    api.getSettings.mockResolvedValue(
      aSettings({
        is_configured: false,
        token_masked: null,
        token_source: 'none',
        platform_token_available: false,
      })
    )
    await renderPanel()
    expect(screen.getByText('Not connected')).toBeInTheDocument()
    expect(screen.getByText(/No platform token is configured/)).toBeInTheDocument()
  })

  it('saves a new token', async () => {
    await renderPanel()
    await userEvent.type(screen.getByLabelText('Your Replicate token'), FULL_TOKEN)
    await userEvent.click(screen.getByRole('button', { name: 'Save token' }))
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({
        api_token: FULL_TOKEN,
      })
    )
    await waitFor(() => expect(screen.getByLabelText('Your Replicate token')).toHaveValue(''))
  })

  it('removes the token by sending an empty one', async () => {
    await renderPanel()
    await userEvent.click(screen.getByRole('button', { name: 'Remove token' }))
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledWith({ api_token: '' }))
  })

  it('shows a refused update with its message', async () => {
    api.updateSettings.mockRejectedValue(refusal('The token was refused by Replicate'))
    await renderPanel()
    await userEvent.type(screen.getByLabelText('Your Replicate token'), 'r8_bad')
    await userEvent.click(screen.getByRole('button', { name: 'Save token' }))
    expect(await screen.findByText('The token was refused by Replicate')).toBeInTheDocument()
  })

  it('tests the connection and shows the account', async () => {
    api.testConnection.mockResolvedValue({
      success: true,
      message: 'ok',
      account: 'maple-makers',
      token_source: 'tenant',
    })
    await renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /Test connection/ }))
    expect(await screen.findByText('Connected as maple-makers.')).toBeInTheDocument()
  })

  it('tests the connection and shows a failure', async () => {
    api.testConnection.mockResolvedValue({
      success: false,
      message: 'Replicate refused the token',
      account: null,
      token_source: 'tenant',
    })
    await renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /Test connection/ }))
    expect(await screen.findByText('Replicate refused the token')).toBeInTheDocument()
  })
})

describe('ReplicateSettings budget', () => {
  it('shows month-to-date spend as a string, jobs and concurrency', async () => {
    await renderPanel()
    expect(screen.getByText('Spent this month:').parentElement).toHaveTextContent(
      'Spent this month: $3.4100 USD'
    )
    expect(screen.getByText('Jobs this month:').parentElement).toHaveTextContent(
      'Jobs this month: 12'
    )
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
    expect(screen.getByLabelText('Monthly budget (USD)')).toHaveValue('25.00')
    expect(screen.getByText(/Current budget:/)).toHaveTextContent('Current budget: $25.00 USD')
    expect(screen.getByText(/Current budget:/)).not.toHaveTextContent('USD USD')
  })

  it('lists usage by month', async () => {
    await renderPanel()
    expect(await screen.findByText('2026-10')).toBeInTheDocument()
    expect(screen.getByText('$0.1200')).toBeInTheDocument()
  })

  it.each(['abc', '1.234'])('refuses the budget %s', async (value) => {
    await renderPanel()
    const input = screen.getByLabelText('Monthly budget (USD)')
    await userEvent.clear(input)
    await userEvent.type(input, value)
    await userEvent.click(screen.getByRole('button', { name: 'Save budget' }))
    expect(await screen.findByText(/at most two decimals/)).toBeInTheDocument()
    expect(api.updateSettings).not.toHaveBeenCalled()
  })

  it('saves 12.50 as a string', async () => {
    await renderPanel()
    const input = screen.getByLabelText('Monthly budget (USD)')
    await userEvent.clear(input)
    await userEvent.type(input, '12.50')
    await userEvent.click(screen.getByRole('button', { name: 'Save budget' }))
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({
        monthly_budget: '12.50',
      })
    )
  })

  it('clears the budget', async () => {
    await renderPanel()
    await userEvent.click(screen.getByRole('button', { name: 'No limit' }))
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledWith({ clear_budget: true }))
  })
})

describe('ReplicateSettings model overrides', () => {
  it('shows one row per capability with its default model and price', async () => {
    await renderPanel()
    const row = await screen.findByTestId('override-row-concept_image')
    expect(within(row).getByText('black-forest-labs/flux-schnell')).toBeInTheDocument()
    expect(within(row).getByText(/\$0\.003/)).toBeInTheDocument()
    expect(screen.getByTestId('override-row-image_edit')).toBeInTheDocument()
  })

  it('refuses the version "latest"', async () => {
    await renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: 'Override Concept image' }))
    const version = screen.getByLabelText('Version')
    await userEvent.clear(version)
    await userEvent.type(version, 'latest')
    await userEvent.click(screen.getByRole('button', { name: 'Save override' }))
    expect(await screen.findByText(/"latest" is not allowed/)).toBeInTheDocument()
    expect(api.updateSettings).not.toHaveBeenCalled()
  })

  it('saves an override with its price as a string', async () => {
    await renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: 'Override Concept image' }))
    const model = screen.getByLabelText('Model')
    await userEvent.clear(model)
    await userEvent.type(model, 'owner/better-model')
    const version = screen.getByLabelText('Version')
    await userEvent.clear(version)
    await userEvent.type(version, VERSION)
    await userEvent.selectOptions(screen.getByLabelText('Price unit'), 'per_run')
    await userEvent.type(screen.getByLabelText('Price (USD)'), '0.05')
    await userEvent.click(screen.getByRole('button', { name: 'Save override' }))
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({
        model_overrides: {
          concept_image: {
            model_ref: 'owner/better-model',
            model_version: VERSION,
            price_unit: 'per_run',
            price_usd: '0.05',
            typical_seconds: null,
          },
        },
      })
    )
  })

  it('asks a per-second price for its typical run time', async () => {
    await renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: 'Override Image edit' }))
    expect(screen.queryByLabelText('Typical run time (seconds)')).not.toBeInTheDocument()
    const version = screen.getByLabelText('Version')
    await userEvent.clear(version)
    await userEvent.type(version, 'official')
    await userEvent.selectOptions(screen.getByLabelText('Price unit'), 'per_second')
    await userEvent.type(screen.getByLabelText('Price (USD)'), '0.0014')
    const seconds = screen.getByLabelText('Typical run time (seconds)')
    await userEvent.type(seconds, '0')
    await userEvent.click(screen.getByRole('button', { name: 'Save override' }))
    expect(await screen.findByText(/whole number of seconds/)).toBeInTheDocument()
    expect(api.updateSettings).not.toHaveBeenCalled()
    await userEvent.clear(seconds)
    await userEvent.type(seconds, '20')
    await userEvent.click(screen.getByRole('button', { name: 'Save override' }))
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalled())
    const sent = api.updateSettings.mock.calls[0][0].model_overrides.image_edit
    expect(sent).toMatchObject({
      price_unit: 'per_second',
      price_usd: '0.0014',
      typical_seconds: 20,
    })
  })

  it('clears an override', async () => {
    api.getSettings.mockResolvedValue(
      aSettings({
        model_overrides: {
          image_edit: { model_ref: 'owner/editor', model_version: VERSION },
        },
      })
    )
    await renderPanel()
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Clear override for Image edit',
      })
    )
    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({
        model_overrides: { image_edit: null },
      })
    )
  })
})
