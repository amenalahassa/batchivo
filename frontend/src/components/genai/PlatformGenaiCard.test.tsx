/** The platform Replicate token switch (spec 008, T029). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'
import type { PlatformGenaiSettings } from '@/types/genai'

import { PlatformGenaiCard } from './PlatformGenaiCard'

const api = vi.hoisted(() => ({
  getPlatform: vi.fn(),
  setPlatform: vi.fn(),
}))
vi.mock('@/lib/api/genai', () => ({ genaiApi: api }))

function aPlatform(overrides: Partial<PlatformGenaiSettings> = {}): PlatformGenaiSettings {
  return {
    tenant_id: 't-1',
    platform_token_allowed: false,
    platform_token_available: true,
    all_tenants: false,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PlatformGenaiCard', () => {
  it('toggles the switch and sends the new value', async () => {
    api.getPlatform.mockResolvedValue(aPlatform())
    api.setPlatform.mockResolvedValue(aPlatform({ platform_token_allowed: true }))
    render(<PlatformGenaiCard tenantId="t-1" />)

    expect(screen.getByText('Generative AI')).toBeInTheDocument()
    const toggle = await screen.findByRole('switch', {
      name: 'Allow the platform Replicate token',
    })
    expect(toggle).not.toBeChecked()
    expect(toggle).toBeEnabled()
    expect(screen.queryByText(/No platform token is configured/)).not.toBeInTheDocument()

    await userEvent.click(toggle)
    await waitFor(() => expect(api.setPlatform).toHaveBeenCalledWith('t-1', true))
    await waitFor(() => expect(toggle).toBeChecked())
  })

  it('says when no platform token is configured', async () => {
    api.getPlatform.mockResolvedValue(aPlatform({ platform_token_available: false }))
    render(<PlatformGenaiCard tenantId="t-1" />)
    expect(
      await screen.findByText('No platform token is configured on this server.')
    ).toBeInTheDocument()
  })

  it('disables the switch when every shop is allowed on this install', async () => {
    api.getPlatform.mockResolvedValue(aPlatform({ all_tenants: true }))
    render(<PlatformGenaiCard tenantId="t-1" />)
    const toggle = await screen.findByRole('switch', {
      name: 'Allow the platform Replicate token',
    })
    expect(toggle).toBeDisabled()
    expect(toggle).toBeChecked()
    expect(screen.getByText(/Every shop is allowed/)).toBeInTheDocument()
  })
})
