/**
 * The packaging settings card (T030): two clearances, defaults flagged.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getPackagingSettings, updatePackagingSettings } from '@/lib/api/packaging'
import { PackagingSettings } from './PackagingSettings'

vi.mock('@/lib/api/packaging', () => ({
  getPackagingSettings: vi.fn(),
  updatePackagingSettings: vi.fn(),
}))

const get = vi.mocked(getPackagingSettings)
const put = vi.mocked(updatePackagingSettings)

function renderCard(canEdit = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <PackagingSettings canEdit={canEdit} />
    </QueryClientProvider>,
  )
}

describe('PackagingSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    get.mockResolvedValue({ clearance_mm: '10.0', fragile_clearance_mm: '20.0', configured: false })
    put.mockResolvedValue({ clearance_mm: '12.5', fragile_clearance_mm: '20.0', configured: true })
  })

  it('says the figures are defaults until saved', async () => {
    renderCard()
    expect(await screen.findByText(/These are the defaults/)).toBeInTheDocument()
    expect(screen.getByLabelText('Clearance (mm)')).toHaveValue('10.0')
  })

  it('saves both clearances as decimal strings', async () => {
    renderCard()
    const clearance = await screen.findByLabelText('Clearance (mm)')
    fireEvent.change(clearance, { target: { value: '12.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][0]).toEqual({ clearance_mm: '12.5', fragile_clearance_mm: '20.0' })
  })

  it('refuses a figure with two decimal places', async () => {
    renderCard()
    const clearance = await screen.findByLabelText('Clearance (mm)')
    fireEvent.change(clearance, { target: { value: '12.55' } })

    expect(screen.getByText(/at most one decimal place/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('offers no save to a viewer', async () => {
    renderCard(false)
    await screen.findByLabelText('Clearance (mm)')
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Clearance (mm)')).toBeDisabled()
  })
})
