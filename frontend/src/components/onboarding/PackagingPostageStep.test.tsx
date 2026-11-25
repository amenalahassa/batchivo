/**
 * Onboarding step 5 (spec 006, T032, T050): the catalogue starts all
 * selected and can be thinned or skipped; the carrier is pre-selected from
 * the country or the currency, or the step says why there is none.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { packagingCatalogueApi } from '@/lib/api/packagingCatalogue'
import { postageCatalogueApi } from '@/lib/api/postageCatalogue'
import type { CatalogueItem } from '@/types/packagingCatalogue'
import type { CarriersResponse } from '@/types/postageCatalogue'

import { PackagingPostageStep } from './PackagingPostageStep'

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children: ReactNode
    onValueChange?: (v: string) => void
    value?: string
  }) => (
    <select value={value ?? ''} onChange={(e) => onValueChange?.(e.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))
vi.mock('@/lib/api/packagingCatalogue', () => ({ packagingCatalogueApi: { get: vi.fn() } }))
vi.mock('@/lib/api/postageCatalogue', () => ({ postageCatalogueApi: { carriers: vi.fn() } }))

function item(key: string): CatalogueItem {
  return {
    key,
    name: key,
    kind: 'box',
    inner_length_mm: '100',
    inner_width_mm: '100',
    inner_height_mm: '100',
    wall_mm: '3',
    empty_weight_grams: '60',
    fill_volume_ml: null,
    unit_of_measure: 'each',
    typical_cost: '0.95',
    source: 'estimate',
    present: false,
    present_as: null,
    previously_removed: false,
  }
}

function carriers(overrides: Partial<CarriersResponse> = {}): CarriersResponse {
  return {
    suggested_carrier: 'canada_post',
    candidate_carrier: 'canada_post',
    chosen_from: 'country',
    reason: null,
    current: { carrier: null, default_service: null, tariff_version: null },
    carriers: [
      {
        key: 'canada_post',
        name: 'Canada Post',
        currency: 'CAD',
        usable: true,
        latest_tariff: '2026-09-07',
        source: 'Canada Post consumer prices guide',
        services: [
          { key: 'small_packet', name: 'Small Packet', seeded: false, has_size_limits: true },
          { key: 'lettermail', name: 'Lettermail', seeded: false, has_size_limits: true },
        ],
      },
      {
        key: 'usps',
        name: 'USPS',
        currency: 'USD',
        usable: false,
        latest_tariff: '2026-10-04',
        source: null,
        services: [],
      },
    ],
    ...overrides,
  }
}

function renderStep(onSubmit = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <PackagingPostageStep onSubmit={onSubmit} onBack={vi.fn()} />
    </QueryClientProvider>,
  )
  return onSubmit
}

beforeEach(() => {
  vi.mocked(packagingCatalogueApi.get).mockResolvedValue({
    version: 1,
    as_of: '2026-11-01',
    currency: 'CAD',
    items: [item('box-cube-100'), item('box-cube-150')],
  })
  vi.mocked(postageCatalogueApi.carriers).mockResolvedValue(carriers())
})

describe('PackagingPostageStep', () => {
  it('starts with every catalogue item and the suggested carrier selected', async () => {
    const onSubmit = renderStep()
    expect(await screen.findByRole('checkbox', { name: 'box-cube-100' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'box-cube-150' })).toBeChecked()
    expect(screen.getByTestId('carrier-chosen-from')).toHaveTextContent('country')
    // An unusable carrier (another currency) is not offered.
    expect(screen.queryByRole('option', { name: 'USPS' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Finish setup/ }))
    expect(onSubmit).toHaveBeenCalledWith({
      packaging_keys: ['box-cube-100', 'box-cube-150'],
      carrier: 'canada_post',
      services: ['small_packet', 'lettermail'],
      default_service: null,
    })
  })

  it('sends only what is left selected, and the default service', async () => {
    const onSubmit = renderStep()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'box-cube-150' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Lettermail' }))
    const [, defaultSelect] = screen.getAllByRole('combobox')
    fireEvent.change(defaultSelect, { target: { value: 'canada_post:small_packet' } })
    fireEvent.click(screen.getByRole('button', { name: /Finish setup/ }))
    expect(onSubmit).toHaveBeenCalledWith({
      packaging_keys: ['box-cube-100'],
      carrier: 'canada_post',
      services: ['small_packet'],
      default_service: 'canada_post:small_packet',
    })
  })

  it('says the carrier came from the currency when there is no country', async () => {
    vi.mocked(postageCatalogueApi.carriers).mockResolvedValue(carriers({ chosen_from: 'currency' }))
    renderStep()
    expect(await screen.findByTestId('carrier-chosen-from')).toHaveTextContent('books currency')
  })

  it('explains why there is no carrier and adds no postage', async () => {
    vi.mocked(postageCatalogueApi.carriers).mockResolvedValue(
      carriers({
        suggested_carrier: null,
        candidate_carrier: 'usps',
        reason: 'carrier_currency_mismatch',
      }),
    )
    const onSubmit = renderStep()
    expect(await screen.findByTestId('carrier-reason')).toHaveTextContent(
      'prices in a different currency',
    )
    expect(screen.queryByTestId('carrier-services')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Finish setup/ }))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ carrier: null, services: [] }),
    )
  })

  it('can be skipped', async () => {
    const onSubmit = renderStep()
    fireEvent.click(await screen.findByRole('button', { name: 'Skip for now' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ skip: true }))
  })
})
