/**
 * The one-time catalogue seeding notice (spec 006, T025, FR-010, FR-022).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { packagingCatalogueApi } from '@/lib/api/packagingCatalogue'
import type { CatalogueNotice as Notice } from '@/types/packagingCatalogue'

import { CatalogueNotice } from './CatalogueNotice'

vi.mock('@/lib/api/packagingCatalogue', () => ({
  packagingCatalogueApi: { notice: vi.fn(), acknowledge: vi.fn() },
}))
const api = vi.mocked(packagingCatalogueApi)

const CARRIERS = [
  { key: 'canada_post', name: 'Canada Post', currency: 'CAD', usable: true, latest_tariff: null, source: null, services: [] },
]

function renderNotice(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

const PACKAGING: Notice = {
  packaging: {
    version: 1,
    applied_at: '2026-11-04',
    added: ['box-cube-100', 'box-cube-150'],
    skipped: [{ key: 'mailer-padded-180', reason: 'name_in_use' }],
  },
}

beforeEach(() => {
  api.notice.mockReset()
  api.acknowledge.mockReset().mockResolvedValue(undefined)
})

describe('CatalogueNotice packaging', () => {
  it('lists what was added and what was skipped, with the reason', async () => {
    api.notice.mockResolvedValue(PACKAGING)
    renderNotice(<CatalogueNotice part="packaging" />)
    expect(await screen.findByText(/2 standard packaging items added/)).toBeInTheDocument()
    expect(screen.getByTestId('notice-skipped')).toHaveTextContent(
      'mailer-padded-180: skipped, you already have an item with that name',
    )
  })

  it('dismisses', async () => {
    api.notice.mockResolvedValueOnce(PACKAGING).mockResolvedValue({})
    renderNotice(<CatalogueNotice part="packaging" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(api.acknowledge).toHaveBeenCalledWith('packaging'))
    await waitFor(() =>
      expect(screen.queryByTestId('catalogue-notice-packaging')).not.toBeInTheDocument(),
    )
  })

  it('shows nothing without a pending notice', async () => {
    api.notice.mockResolvedValue({})
    renderNotice(<CatalogueNotice part="packaging" />)
    await waitFor(() => expect(api.notice).toHaveBeenCalled())
    expect(screen.queryByTestId('catalogue-notice-packaging')).not.toBeInTheDocument()
  })
})

describe('CatalogueNotice postage', () => {
  it('names the carrier and that it came from the currency', async () => {
    api.notice.mockResolvedValue({
      postage: {
        carrier: 'canada_post',
        chosen_from: 'currency',
        tariff_version: '2026-09-07',
        applied_at: '2026-11-04',
        added: 14,
        superseded: 0,
        skipped: [],
        reason: null,
      },
    })
    renderNotice(<CatalogueNotice part="postage" carriers={CARRIERS} />)
    const notice = await screen.findByTestId('catalogue-notice-postage')
    expect(notice).toHaveTextContent('Canada Post')
    expect(notice).toHaveTextContent('chosen from your books currency')
    expect(notice).toHaveTextContent('2026-09-07')
  })

  it('says why nothing was added and points to adding a profile', async () => {
    api.notice.mockResolvedValue({
      postage: {
        carrier: null,
        chosen_from: 'currency',
        tariff_version: null,
        applied_at: '2026-11-04',
        added: 0,
        superseded: 0,
        skipped: [],
        reason: 'no_carrier_for_currency',
      },
    })
    const onAddProfile = vi.fn()
    renderNotice(<CatalogueNotice part="postage" onAddProfile={onAddProfile} />)
    expect(await screen.findByText(/no carrier tariff priced in your books currency/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add profile' }))
    expect(onAddProfile).toHaveBeenCalled()
  })
})
