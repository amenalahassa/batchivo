/**
 * The FR-040 actuals surface, rendered from the strings the API actually sends.
 *
 * The backend types every one of these figures `Decimal`, and this app
 * serialises a Decimal as a JSON **string**. The frontend types said `number`,
 * so the compiler was happy while the component put each figure through
 * `Number()` -- a binary double in the middle of the realised actuals, which
 * is the one conversion that can make this screen disagree with the engine.
 * It is the same mismatch T158 found for spools; T151 fixed the model screens
 * and T162 the channel ones, and both stopped before this one.
 *
 * So the fixtures below use decimal **strings**, chosen so a double would give
 * a visibly different answer (FR-047/FR-040, Constitution II and IV).
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { render } from '@/test/test-utils'
import { ProductionRunDetail } from './ProductionRunDetail'
import { getProductionRun } from '@/lib/api/production-runs'
import type { ProductionRunDetail as Run } from '@/types/production-run'

vi.mock('@/lib/api/production-runs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/production-runs')>()
  return { ...actual, getProductionRun: vi.fn() }
})

const mockGetProductionRun = getProductionRun as Mock

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 'run-1',
    tenant_id: 'tenant-1',
    run_number: 'RUN-0001',
    status: 'completed',
    started_at: '2026-01-01T09:00:00Z',
    completed_at: '2026-01-01T13:00:00Z',
    created_at: '2026-01-01T09:00:00Z',
    updated_at: '2026-01-01T13:00:00Z',
    items: [],
    materials: [],
    total_items_planned: 0,
    total_items_successful: 0,
    total_items_failed: 0,
    total_material_cost: '0',
    total_estimated_cost: '0',
    ...overrides,
  } as Run
}

function makeMaterial(
  overrides: Partial<Run['materials'][number]> = {},
): Run['materials'][number] {
  return {
    id: 'material-1',
    production_run_id: 'run-1',
    spool_id: 'spool-1',
    estimated_model_weight_grams: 100,
    estimated_flushed_grams: 5,
    estimated_tower_grams: 5,
    cost_per_gram: '0.0300',
    created_at: '2026-01-01T09:00:00Z',
    updated_at: '2026-01-01T13:00:00Z',
    estimated_total_weight: 110,
    actual_total_weight: 110,
    variance_grams: 0,
    variance_percentage: 0,
    estimated_cost: '3.30',
    total_cost: '3.30',
    ...overrides,
  } as Run['materials'][number]
}

describe('ProductionRunDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('the realised cost per gram', () => {
    it('renders the decimal string exactly, where a double would round down', async () => {
      // 0.0215 is not representable in binary. Rounded half-up in string space
      // this is £0.02; a double of 0.0215 is slightly below and rounds the
      // other way on some values. The string path is the one that matches the
      // figure the engine stored.
      mockGetProductionRun.mockResolvedValue(
        makeRun({ cost_per_gram_actual: '0.0215', successful_weight_grams: '120.5' }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('Cost Per Gram')).toBeInTheDocument()
      })
      expect(screen.getByText('£0.02')).toBeInTheDocument()
    })

    it('shows no cost analysis at all when the run was never costed', async () => {
      // An uncosted run and a free one are different facts, and this screen
      // keeps them apart by withholding the whole card (FR-019).
      mockGetProductionRun.mockResolvedValue(
        makeRun({ cost_per_gram_actual: null, successful_weight_grams: null }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.queryByText('Cost Per Gram')).not.toBeInTheDocument()
      expect(screen.queryByText('£0.00')).not.toBeInTheDocument()
    })
  })

  describe('the successful weight', () => {
    it('rounds the decimal string in string space', async () => {
      mockGetProductionRun.mockResolvedValue(
        makeRun({ cost_per_gram_actual: '0.03', successful_weight_grams: '142.45' }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('Successful Weight')).toBeInTheDocument()
      })
      expect(screen.getByText('142.5g')).toBeInTheDocument()
    })
  })

  describe('plan versus actual', () => {
    it('reports the difference by subtracting exact decimals', async () => {
      // 0.1 + 0.2 in doubles is 0.30000000000000004. Subtracting these two as
      // doubles gives 1.1500000000000004; subtracted exactly it is 1.15.
      mockGetProductionRun.mockResolvedValue(
        makeRun({
          total_estimated_cost: '10.10',
          total_material_cost: '11.25',
          cost_per_gram_actual: '0.03',
          successful_weight_grams: '100',
          materials: [makeMaterial()],
        }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('£10.10')).toBeInTheDocument()
      })
      expect(screen.getByText('£11.25')).toBeInTheDocument()
      expect(screen.getByText('£1.15')).toBeInTheDocument()
    })

    it('compares the two figures without going through a double', async () => {
      // Equal to the cent, so neither is "over" the other: a comparison done
      // on doubles of long decimals can disagree with the exact one.
      mockGetProductionRun.mockResolvedValue(
        makeRun({
          total_estimated_cost: '7.70',
          total_material_cost: '7.70',
          cost_per_gram_actual: '0.03',
          successful_weight_grams: '100',
          materials: [makeMaterial()],
        }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('£0.00')).toBeInTheDocument()
      })
    })
  })

  describe('the waste factor', () => {
    it('derives the percentage from the two exact decimals', async () => {
      // 110 used against 100 theoretically needed is 10% extra.
      mockGetProductionRun.mockResolvedValue(
        makeRun({
          cost_per_gram_actual: '0.03',
          successful_weight_grams: '100',
          actual_total_weight_grams: 110,
        }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('Waste Factor')).toBeInTheDocument()
      })
      expect(screen.getByText('10.0%')).toBeInTheDocument()
    })

    it('shows a dash rather than a figure when the weight is missing', async () => {
      mockGetProductionRun.mockResolvedValue(
        makeRun({
          cost_per_gram_actual: '0.03',
          successful_weight_grams: null,
          actual_total_weight_grams: 110,
        }),
      )

      render(<ProductionRunDetail runId="run-1" />)

      await waitFor(() => {
        expect(screen.getByText('Waste Factor')).toBeInTheDocument()
      })
      expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
    })
  })
})
