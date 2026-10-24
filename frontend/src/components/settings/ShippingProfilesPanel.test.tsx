/**
 * Postage can be managed from the console (T245, FR-024).
 *
 * The shipping-profile hooks had no screen. The panel lists what is in force,
 * lets an admin add or reprice postage -- saying that a repricing takes effect
 * from today and leaves placed orders alone (FR-003) -- and is read-only below
 * admin (FR-007a).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ShippingProfilesPanel } from './ShippingProfilesPanel'
import { feeRulesApi } from '@/lib/api/feeRules'
import type { ShippingProfile } from '@/types/pricing'

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: {
    listShippingProfiles: vi.fn(),
    createShippingProfile: vi.fn(),
    updateShippingProfile: vi.fn(),
    deleteShippingProfile: vi.fn(),
  },
}))

const api = vi.mocked(feeRulesApi)

function profile(overrides: Partial<ShippingProfile> = {}): ShippingProfile {
  return {
    id: 'profile-1',
    tenant_id: 'tenant-1',
    name: 'UK small parcel',
    destination_zone: 'UK',
    weight_bracket_min_grams: '0',
    weight_bracket_max_grams: '1000',
    postage_cost: '3.85',
    carrier: 'Royal Mail',
    effective_from: '2026-09-01',
    effective_to: null,
    ...overrides,
  }
}

function renderPanel(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('ShippingProfilesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listShippingProfiles.mockResolvedValue({ profiles: [profile()], total: 1 })
    api.createShippingProfile.mockResolvedValue(profile({ id: 'profile-2' }))
    api.updateShippingProfile.mockResolvedValue(profile())
  })

  it('lists the postage in force with its zone, bracket and date', async () => {
    renderPanel(<ShippingProfilesPanel />)

    const row = within(await screen.findByTestId('shipping-profile-profile-1'))
    expect(row.getByText('UK small parcel')).toBeInTheDocument()
    expect(row.getByText('0–1000 g')).toBeInTheDocument()
    expect(row.getByText('£3.85')).toBeInTheDocument()
    expect(row.getByText('from 2026-09-01')).toBeInTheDocument()
  })

  it('says when there is no postage, rather than showing nothing', async () => {
    api.listShippingProfiles.mockResolvedValue({ profiles: [], total: 0 })
    renderPanel(<ShippingProfilesPanel canEdit />)

    expect(await screen.findByTestId('shipping-profiles-empty')).toBeInTheDocument()
  })

  it('lets an admin add postage, sent as decimal strings', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: /Add postage/ }))
    await user.type(screen.getByLabelText('Name'), 'EU parcel')
    await user.type(screen.getByLabelText('Zone'), 'EU')
    await user.type(screen.getByLabelText('Postage paid'), '9.40')
    await user.click(screen.getByRole('button', { name: 'Save postage' }))

    await waitFor(() => expect(api.createShippingProfile).toHaveBeenCalled())
    expect(api.createShippingProfile.mock.calls[0][0]).toMatchObject({
      name: 'EU parcel',
      destination_zone: 'EU',
      postage_cost: '9.40',
      weight_bracket_min_grams: '0',
      weight_bracket_max_grams: null,
    })
  })

  it('says a repricing takes effect from today and leaves placed orders alone', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: 'Change UK small parcel' }))
    expect(screen.getByTestId('shipping-supersede-note')).toHaveTextContent(
      'orders already placed keep the postage',
    )
    const postage = screen.getByLabelText('Postage paid')
    await user.clear(postage)
    await user.type(postage, '4.10')
    await user.click(screen.getByRole('button', { name: 'Save postage' }))

    await waitFor(() => expect(api.updateShippingProfile).toHaveBeenCalled())
    expect(api.updateShippingProfile.mock.calls[0][0]).toBe('profile-1')
    expect(api.updateShippingProfile.mock.calls[0][1]).toMatchObject({ postage_cost: '4.10' })
  })

  it('refuses an amount that is not money', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: /Add postage/ }))
    await user.type(screen.getByLabelText('Name'), 'Bad')
    await user.type(screen.getByLabelText('Zone'), 'UK')
    await user.type(screen.getByLabelText('Postage paid'), '3.855')
    await user.click(screen.getByRole('button', { name: 'Save postage' }))

    expect(await screen.findByText(/Enter an amount/)).toBeInTheDocument()
    expect(api.createShippingProfile).not.toHaveBeenCalled()
  })

  it('is read-only below admin', async () => {
    renderPanel(<ShippingProfilesPanel canEdit={false} />)

    await screen.findByTestId('shipping-profile-profile-1')
    expect(screen.queryByRole('button', { name: /Add postage/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change UK small parcel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Stop using UK small parcel' })).toBeDisabled()
  })

  it('does not offer to change a superseded profile', async () => {
    api.listShippingProfiles.mockResolvedValue({
      profiles: [profile({ effective_to: '2026-10-01' })],
      total: 1,
    })
    renderPanel(<ShippingProfilesPanel canEdit />)

    expect(await screen.findByText('2026-09-01 to 2026-10-01')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change UK small parcel' })).toBeDisabled()
  })
})
