/**
 * PackagingSuggestions -- the ranked list, its empty states, and accepting a box.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { render } from '@/test/test-utils'
import { PackagingSuggestions } from './PackagingSuggestions'
import * as packagingApi from '@/lib/api/packaging'
import type { PackagingSuggestions as Advice } from '@/types/packaging'

vi.mock('@/lib/api/packaging', () => ({
  getPackagingSuggestions: vi.fn(),
  acceptPackaging: vi.fn(),
}))

const ranked: Advice = {
  item: { length_mm: '120.0', width_mm: '70.0', height_mm: '30.0', source: 'entered' },
  clearance_mm: '10.0',
  fragile: false,
  suggestions: [
    {
      consumable_id: 'box-s',
      name: 'Box S',
      kind: 'box',
      in_stock: true,
      inner: { length_mm: '150.0', width_mm: '100.0', height_mm: '60.0' },
      orientation: ['length', 'width', 'height'],
      room_mm: { length: '10.0', width: '10.0', height: '10.0' },
      empty_volume_ml: '648.0',
      void_fill: { consumable_id: 'fill', name: 'Paper fill', quantity: 1 },
      wrap: null,
      is_current: false,
    },
    {
      consumable_id: 'box-l',
      name: 'Box L',
      kind: 'box',
      in_stock: false,
      inner: { length_mm: '200.0', width_mm: '150.0', height_mm: '100.0' },
      orientation: ['height', 'width', 'length'],
      room_mm: { length: '50.0', width: '60.0', height: '0.0' },
      empty_volume_ml: '2748.0',
      void_fill: null,
      wrap: null,
      is_current: true,
    },
  ],
  minimum_inner: null,
  warnings: ['incomplete_container:Mailer A4'],
}

async function ask() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /Suggest packaging/ }))
  return user
}

describe('PackagingSuggestions', () => {
  beforeEach(() => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockReset()
    vi.mocked(packagingApi.acceptPackaging).mockReset()
    vi.mocked(packagingApi.acceptPackaging).mockResolvedValue(undefined)
  })

  it('fetches nothing until asked (FR-022)', () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue(ranked)
    render(<PackagingSuggestions productId="p1" canEdit />)
    expect(packagingApi.getPackagingSuggestions).not.toHaveBeenCalled()
  })

  it('lists the boxes best first with orientation, room, empty volume and fill', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue(ranked)
    render(<PackagingSuggestions productId="p1" canEdit />)
    await ask()

    expect(await screen.findByText('1. Box S')).toBeInTheDocument()
    expect(screen.getByText('2. Box L')).toBeInTheDocument()
    expect(screen.getByText(/room 10\.0 \/ 10\.0 \/\s*10\.0 mm · empty 648\.0 ml/)).toBeInTheDocument()
    expect(screen.getByText('Void fill: 1 × Paper fill')).toBeInTheDocument()
    expect(screen.getByText(/Item height along the box length/)).toBeInTheDocument()
    expect(screen.getByText('Out of stock')).toBeInTheDocument()
    expect(screen.getByText('Current')).toBeInTheDocument()
    expect(screen.getByText(/Mailer A4/)).toBeInTheDocument()
  })

  it('shows no cost of its own (FR-021)', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue(ranked)
    const { container } = render(<PackagingSuggestions productId="p1" canEdit />)
    await ask()
    await screen.findByText('1. Box S')
    expect(container.textContent).not.toMatch(/[£$€]|cost/i)
  })

  it('accepts a box for the variant it was asked for', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue(ranked)
    render(<PackagingSuggestions productId="p1" variantId="v1" canEdit />)
    const user = await ask()
    await screen.findByText('1. Box S')
    expect(packagingApi.getPackagingSuggestions).toHaveBeenCalledWith('p1', 'v1')
    // The current box offers no Accept; the other one does.
    const buttons = screen.getAllByRole('button', { name: /Accept/ })
    expect(buttons).toHaveLength(1)
    await user.click(buttons[0])
    await waitFor(() =>
      expect(packagingApi.acceptPackaging).toHaveBeenCalledWith('p1', {
        consumable_id: 'box-s',
        quantity: 1,
        variant_id: 'v1',
      }),
    )
  })

  it('offers no Accept to a viewer', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue(ranked)
    render(<PackagingSuggestions productId="p1" canEdit={false} />)
    await ask()
    await screen.findByText('1. Box S')
    expect(screen.queryByRole('button', { name: /Accept/ })).not.toBeInTheDocument()
  })

  it('asks for dimensions first', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue({
      ...ranked,
      item: null,
      suggestions: [],
      warnings: ['dimensions_required'],
    })
    render(<PackagingSuggestions productId="p1" canEdit dimensionsAnchor="dims" />)
    await ask()
    expect(await screen.findByText(/Record this item's dimensions first/)).toBeInTheDocument()
  })

  it('says nothing fits and gives the minimum inner size', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue({
      ...ranked,
      suggestions: [],
      minimum_inner: { length_mm: '320.0', width_mm: '320.0', height_mm: '320.0' },
      warnings: ['nothing_fits'],
    })
    render(<PackagingSuggestions productId="p1" canEdit />)
    await ask()
    expect(
      await screen.findByText(/A box would need at least 320\.0 × 320\.0 × 320\.0 mm inside/),
    ).toBeInTheDocument()
    // Spec 006, FR-007: the operator is sent where boxes are added.
    expect(screen.getByRole('link', { name: 'Add one on the Packaging page' })).toHaveAttribute(
      'href',
      '/packaging',
    )
  })

  it('marks a fragile item and names the wrap', async () => {
    vi.mocked(packagingApi.getPackagingSuggestions).mockResolvedValue({
      ...ranked,
      fragile: true,
      clearance_mm: '20.0',
      suggestions: [{ ...ranked.suggestions[0], wrap: { consumable_id: 'w', name: 'Bubble wrap' } }],
    })
    render(<PackagingSuggestions productId="p1" canEdit />)
    await ask()
    expect(await screen.findByText('Fragile')).toBeInTheDocument()
    expect(screen.getByText(/Wrap in Bubble wrap/)).toBeInTheDocument()
    expect(screen.getByText('20.0 mm clearance on every side')).toBeInTheDocument()
  })
})
