/**
 * DimensionsEditor -- recording an item's size, and where it came from (FR-001 to FR-004).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { render } from '@/test/test-utils'
import { DimensionsEditor } from './DimensionsEditor'
import * as packagingApi from '@/lib/api/packaging'
import type { Dimensions } from '@/types/packaging'

vi.mock('@/lib/api/packaging', () => ({
  setProductDimensions: vi.fn(),
  setVariantDimensions: vi.fn(),
  setModelDimensions: vi.fn(),
}))

const entered: Dimensions = {
  length_mm: '120.0',
  width_mm: '80.0',
  height_mm: '45.0',
  source: 'entered',
  source_file_id: null,
  set_at: '2026-10-25T10:00:00Z',
  inherited: false,
}

const target = { kind: 'product' as const, productId: 'p1' }

describe('DimensionsEditor', () => {
  beforeEach(() => {
    vi.mocked(packagingApi.setProductDimensions).mockReset()
    vi.mocked(packagingApi.setProductDimensions).mockResolvedValue(entered)
  })

  it('shows the figures and that the operator entered them', () => {
    render(<DimensionsEditor target={target} dimensions={entered} canEdit />)
    expect(screen.getByText('120.0 × 80.0 × 45.0 mm')).toBeInTheDocument()
    expect(screen.getByText(/^Entered/)).toBeInTheDocument()
  })

  it('names the file a measurement came from', () => {
    render(
      <DimensionsEditor
        target={target}
        dimensions={{ ...entered, source: 'measured', source_file_id: 'f1' }}
        fileNames={{ f1: 'block.stl' }}
        canEdit
      />,
    )
    expect(screen.getByText(/Measured from block\.stl/)).toBeInTheDocument()
  })

  it('marks a variant showing the product figures as inherited', () => {
    render(
      <DimensionsEditor
        target={{ kind: 'variant', productId: 'p1', variantId: 'v1' }}
        dimensions={{ ...entered, inherited: true }}
        canEdit
      />,
    )
    expect(screen.getByText('Inherited from product')).toBeInTheDocument()
  })

  it('saves the three figures as decimal strings', async () => {
    const user = userEvent.setup()
    render(<DimensionsEditor target={target} dimensions={null} canEdit />)
    await user.type(screen.getByLabelText('Length (mm)'), '120')
    await user.type(screen.getByLabelText('Width (mm)'), '80.5')
    await user.type(screen.getByLabelText('Height (mm)'), '45')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(packagingApi.setProductDimensions).toHaveBeenCalledWith('p1', {
        length_mm: '120',
        width_mm: '80.5',
        height_mm: '45',
      }),
    )
  })

  it('refuses zero, a non-number and two decimals, naming the field', async () => {
    const user = userEvent.setup()
    render(<DimensionsEditor target={target} dimensions={null} canEdit />)
    await user.type(screen.getByLabelText('Length (mm)'), '0')
    await user.type(screen.getByLabelText('Width (mm)'), 'abc')
    await user.type(screen.getByLabelText('Height (mm)'), '12.34')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Length must be greater than 0')).toBeInTheDocument()
    expect(screen.getByText(/^Width must be a number/)).toBeInTheDocument()
    expect(screen.getByText(/^Height must be a number/)).toBeInTheDocument()
    expect(packagingApi.setProductDimensions).not.toHaveBeenCalled()
  })

  it('offers no Save to a viewer', () => {
    render(<DimensionsEditor target={target} dimensions={entered} canEdit={false} />)
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Length (mm)')).not.toBeInTheDocument()
    expect(screen.getByText('120.0 × 80.0 × 45.0 mm')).toBeInTheDocument()
  })

  it('offers a differing measurement and adopts it on request', async () => {
    const user = userEvent.setup()
    render(
      <DimensionsEditor
        target={target}
        dimensions={entered}
        canEdit
        offer={{ fileId: 'f9', fileName: 'block.stl', length_mm: '40.0', width_mm: '30.0', height_mm: '20.0' }}
      />,
    )
    expect(screen.getByText('Measured 40.0 × 30.0 × 20.0 mm from block.stl')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use these' }))
    await waitFor(() =>
      expect(packagingApi.setProductDimensions).toHaveBeenCalledWith('p1', {
        length_mm: null,
        width_mm: null,
        height_mm: null,
        adopt_file_id: 'f9',
      }),
    )
  })

  it('does not offer a measurement equal to the figures in force', () => {
    render(
      <DimensionsEditor
        target={target}
        dimensions={entered}
        canEdit
        offer={{ fileId: 'f9', fileName: 'block.stl', length_mm: '120.0', width_mm: '80.0', height_mm: '45.0' }}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Use these' })).not.toBeInTheDocument()
  })
})
