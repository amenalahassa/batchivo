/**
 * Postage can be managed from the console (T245, FR-024).
 *
 * The shipping-profile hooks had no screen. The panel lists what is in force,
 * lets an admin add or reprice postage -- saying that a repricing takes effect
 * from today and leaves placed orders alone (FR-003) -- and is read-only below
 * admin (FR-007a).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ShippingProfilesPanel } from './ShippingProfilesPanel'
import { feeRulesApi } from '@/lib/api/feeRules'
import type { ShippingProfile } from '@/types/pricing'
import { postageCatalogueApi } from '@/lib/api/postageCatalogue'
import { packagingCatalogueApi } from '@/lib/api/packagingCatalogue'
import type { CarriersResponse } from '@/types/postageCatalogue'

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: {
    listShippingProfiles: vi.fn(),
    createShippingProfile: vi.fn(),
    updateShippingProfile: vi.fn(),
    deleteShippingProfile: vi.fn(),
  },
}))

const api = vi.mocked(feeRulesApi)

// Spec 006: the carrier section and the postage notice read these.
vi.mock('@/lib/api/postageCatalogue', () => ({
  postageCatalogueApi: {
    carriers: vi.fn(),
    tariffUpdates: vi.fn(),
    apply: vi.fn(),
    removeService: vi.fn(),
    setDefaultService: vi.fn(),
  },
}))
vi.mock('@/lib/api/packagingCatalogue', () => ({
  packagingCatalogueApi: { notice: vi.fn(), acknowledge: vi.fn() },
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
    disabled,
  }: {
    children: ReactNode
    onValueChange?: (v: string) => void
    value?: string
    disabled?: boolean
  }) => {
    // The trigger's aria-label names the native select a test finds.
    const items = Array.isArray(children) ? children : [children]
    const trigger = items.find(
      (c: unknown) => (c as { props?: { 'aria-label'?: string } })?.props?.['aria-label'],
    ) as { props: { 'aria-label': string } } | undefined
    return (
      <select
        aria-label={trigger?.props['aria-label']}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onValueChange?.(e.target.value)}
      >
        <option value="" />
        {children}
      </select>
    )
  },
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))
const postage = vi.mocked(postageCatalogueApi)
const notices = vi.mocked(packagingCatalogueApi)

function carriersResponse(overrides: Partial<CarriersResponse> = {}): CarriersResponse {
  return {
    suggested_carrier: 'canada_post',
    candidate_carrier: 'canada_post',
    chosen_from: 'currency',
    reason: null,
    current: { carrier: 'canada_post', default_service: null, tariff_version: '2026-09-07' },
    carriers: [
      {
        key: 'canada_post',
        name: 'Canada Post',
        currency: 'CAD',
        usable: true,
        latest_tariff: '2026-09-07',
        source: 'Canada Post prices guide',
        services: [
          { key: 'small_packet', name: 'Small Packet', seeded: true, has_size_limits: true },
          { key: 'lettermail', name: 'Lettermail', seeded: false, has_size_limits: true },
        ],
      },
      {
        key: 'la_poste',
        name: 'La Poste',
        currency: 'CAD',
        usable: true,
        latest_tariff: '2026-01-01',
        source: 'laposte.fr',
        services: [],
      },
    ],
    ...overrides,
  }
}

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
    postage.carriers.mockResolvedValue(carriersResponse())
    postage.tariffUpdates.mockResolvedValue([])
    postage.apply.mockResolvedValue({ added: 1, superseded: 0, skipped: [] })
    postage.removeService.mockResolvedValue(undefined)
    postage.setDefaultService.mockResolvedValue({ carrier: 'canada_post', default_service: null })
    notices.notice.mockResolvedValue({})
    notices.acknowledge.mockResolvedValue(undefined)
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

  // Bug postage-error-raw-json: the alert showed axios' "Request failed with
  // status code 422" while the reason was only readable in the raw response.
  it("shows the server's reason when postage is not saved", async () => {
    const reason = '"Canada colis" already covers 0 g to any weight in zone CA.'
    api.createShippingProfile.mockRejectedValue(
      new AxiosError('Request failed with status code 422', 'ERR_BAD_REQUEST', undefined, undefined, {
        status: 422,
        statusText: 'Unprocessable Content',
        data: { detail: reason },
        headers: {},
        config: { headers: new AxiosHeaders() },
      })
    )
    const user = userEvent.setup({ delay: null })
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: /Add postage/ }))
    await user.type(screen.getByLabelText('Name'), 'Canada colis 2')
    await user.type(screen.getByLabelText('Zone'), 'CA')
    await user.type(screen.getByLabelText('Postage paid'), '9.40')
    await user.click(screen.getByRole('button', { name: 'Save postage' }))

    expect(await screen.findByText(reason)).toBeInTheDocument()
    expect(screen.queryByText(/status code 422/)).not.toBeInTheDocument()
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

  it('sends a size class and volumetric divisor as decimal strings (T054)', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: /Add postage/ }))
    await user.type(screen.getByLabelText('Name'), 'Large letter')
    await user.type(screen.getByLabelText('Zone'), 'UK')
    await user.type(screen.getByLabelText('Postage paid'), '2.70')
    await user.type(screen.getByLabelText('Max length (mm)'), '353')
    await user.type(screen.getByLabelText('Max width (mm)'), '250')
    await user.type(screen.getByLabelText('Max height (mm)'), '25')
    await user.type(screen.getByLabelText('Volumetric divisor'), '5000')
    await user.click(screen.getByRole('button', { name: 'Save postage' }))

    await waitFor(() => expect(api.createShippingProfile).toHaveBeenCalled())
    expect(api.createShippingProfile.mock.calls[0][0]).toMatchObject({
      max_length_mm: '353',
      max_width_mm: '250',
      max_height_mm: '25',
      volumetric_divisor: '5000',
    })
  })

  it('refuses a size class with a limit missing', async () => {
    const user = userEvent.setup({ delay: null })
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: /Add postage/ }))
    await user.type(screen.getByLabelText('Name'), 'Large letter')
    await user.type(screen.getByLabelText('Zone'), 'UK')
    await user.type(screen.getByLabelText('Postage paid'), '2.70')
    await user.type(screen.getByLabelText('Max length (mm)'), '353')
    await user.click(screen.getByRole('button', { name: 'Save postage' }))

    expect(await screen.findByText('Give all three size limits, or none')).toBeInTheDocument()
    expect(api.createShippingProfile).not.toHaveBeenCalled()
  })

  it('shows a profile’s size class beside its weight', async () => {
    api.listShippingProfiles.mockResolvedValue({
      profiles: [
        profile({ max_length_mm: '353.0', max_width_mm: '250.0', max_height_mm: '25.0' }),
      ],
      total: 1,
    })
    renderPanel(<ShippingProfilesPanel />)
    expect(await screen.findByText('≤ 353.0 × 250.0 × 25.0 mm')).toBeInTheDocument()
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

  // ============================================
  // Spec 006: carrier postage (T038, T052)
  // ============================================

  it('shows the carrier, its services and which are in use', async () => {
    renderPanel(<ShippingProfilesPanel canEdit />)

    expect(await screen.findByTestId('carrier-current')).toHaveTextContent(
      'Canada Post, tariff of 2026-09-07',
    )
    const services = within(screen.getByTestId('carrier-services'))
    expect(services.getByText('In use')).toBeInTheDocument()
    expect(services.getByRole('button', { name: 'Remove Small Packet' })).toBeInTheDocument()
    expect(services.getByRole('button', { name: 'Add Lettermail' })).toBeInTheDocument()
  })

  it('labels a seeded row as a default with its source and tariff date', async () => {
    api.listShippingProfiles.mockResolvedValue({
      profiles: [
        profile({
          id: 'seeded-1',
          name: 'Small Packet us 0-250 g',
          carrier: 'Canada Post',
          catalogue_carrier: 'canada_post',
          service: 'small_packet',
          tariff_version: '2026-09-07',
          source: 'Canada Post prices guide',
        }),
      ],
      total: 1,
    })
    renderPanel(<ShippingProfilesPanel canEdit />)

    const seeded = await screen.findByTestId('seeded-profile')
    expect(seeded).toHaveTextContent('Canada Post')
    expect(seeded).toHaveTextContent('default')
    expect(seeded).toHaveTextContent('Canada Post prices guide, tariff of 2026-09-07')
  })

  it('sets the default service', async () => {
    const user = userEvent.setup()
    renderPanel(<ShippingProfilesPanel canEdit />)

    const select = await screen.findByRole('combobox', { name: 'Default service' })
    await user.selectOptions(select, 'canada_post:small_packet')
    await waitFor(() =>
      expect(postage.setDefaultService).toHaveBeenCalledWith('canada_post:small_packet'),
    )
  })

  it('offers a newer tariff and accepts it', async () => {
    const user = userEvent.setup()
    postage.tariffUpdates.mockResolvedValue([
      {
        carrier: 'canada_post',
        current: '2026-09-07',
        latest: '2027-01-11',
        effective_from: '2027-01-11',
        source: 'Canada Post 2027',
      },
    ])
    renderPanel(<ShippingProfilesPanel canEdit />)

    expect(await screen.findByTestId('tariff-update')).toHaveTextContent('2027-01-11')
    await user.click(screen.getByRole('button', { name: 'Use the new tariff' }))
    await waitFor(() =>
      expect(postage.apply).toHaveBeenCalledWith({
        carrier: 'canada_post',
        tariff_version: '2027-01-11',
      }),
    )
  })

  it('switches carrier after confirming', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Switch carrier' }),
      'la_poste',
    )
    await user.click(screen.getByRole('button', { name: 'Switch' }))
    await waitFor(() =>
      expect(postage.apply).toHaveBeenCalledWith({ carrier: 'la_poste' }),
    )
  })

  it('removes a service after confirming', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPanel(<ShippingProfilesPanel canEdit />)

    await user.click(await screen.findByRole('button', { name: 'Remove Small Packet' }))
    await waitFor(() => expect(postage.removeService).toHaveBeenCalledWith('small_packet'))
  })

  it('names the carrier in the notice and where it was chosen from', async () => {
    notices.notice.mockResolvedValue({
      postage: {
        carrier: 'canada_post',
        chosen_from: 'country',
        tariff_version: '2026-09-07',
        applied_at: '2026-11-04',
        added: 12,
        superseded: 0,
        skipped: [],
        reason: null,
      },
    })
    renderPanel(<ShippingProfilesPanel canEdit />)

    const notice = await screen.findByTestId('catalogue-notice-postage')
    expect(notice).toHaveTextContent('12 postage profiles added from the Canada Post tariff')
    expect(notice).toHaveTextContent(/chosen from your shop.s country/)
  })

  it('explains a currency without a carrier and points to adding a profile (FR-022)', async () => {
    const user = userEvent.setup()
    postage.carriers.mockResolvedValue(
      carriersResponse({
        suggested_carrier: null,
        candidate_carrier: null,
        reason: 'no_carrier_for_currency',
        current: { carrier: null, default_service: null, tariff_version: null },
      }),
    )
    renderPanel(<ShippingProfilesPanel canEdit />)

    const reason = await screen.findByTestId('carrier-reason')
    expect(reason).toHaveTextContent('no carrier tariff priced in your books currency')
    await user.click(within(reason).getByRole('button', { name: 'Add postage' }))
    expect(screen.getByTestId('shipping-profile-form')).toBeInTheDocument()
  })

  it('keeps the carrier section read-only below admin', async () => {
    renderPanel(<ShippingProfilesPanel canEdit={false} />)

    await screen.findByTestId('carrier-services')
    expect(screen.queryByRole('button', { name: 'Remove Small Packet' })).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Default service' })).toBeDisabled()
    expect(screen.queryByRole('combobox', { name: 'Switch carrier' })).not.toBeInTheDocument()
  })
})
