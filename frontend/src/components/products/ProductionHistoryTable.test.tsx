/**
 * The product's production history, costed from the recorded actuals (task T193).
 *
 * This table had three defects in nine lines, and no test, which is why none of
 * them was ever seen.
 *
 * **It did not work.** `estimated_total_cost` is `Optional[Decimal]` on the
 * API, so it arrives as a JSON *string* and the frontend types it `Money`.
 * `0 + "12.50" + "8.00"` is the string `"012.508.00"`, and multiplying that by
 * a variance gives `NaN` — so every cost column was broken for any run with
 * more than one costed item.
 *
 * **It was a second implementation.** The "actual" cost was
 * `estimated * (1 + variance/100) * (successRate/100)`: an estimate scaled by a
 * *weight* variance and a yield, not a recorded actual.
 * `ProductionRunService.record_actual_unit_costs` writes the real figures to
 * `actual_cost_per_unit`, which `ProductionRunDetail` renders — so the two
 * screens answered differently about one run (Constitution III, SC-008).
 *
 * **It read a missing cost as zero**, which FR-019 forbids.
 *
 * Every fixture below therefore uses decimal **strings**, with amounts chosen
 * so string concatenation and float arithmetic both give visibly wrong answers.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { render } from '@/test/test-utils'
import { ProductionHistoryTable } from './ProductionHistoryTable'
import { listProductionRuns } from '@/lib/api/production-runs'
import type { ProductionRunDetail, ProductionRunItem } from '@/types/production-run'

vi.mock('@/lib/api/production-runs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/production-runs')>()
  return { ...actual, listProductionRuns: vi.fn() }
})

const mockListProductionRuns = listProductionRuns as Mock

const MODEL_ID = 'model-1'

function makeItem(overrides: Partial<ProductionRunItem> = {}): ProductionRunItem {
  return {
    id: 'item-1',
    production_run_id: 'run-1',
    model_id: MODEL_ID,
    quantity: 1,
    successful_quantity: 1,
    failed_quantity: 0,
    created_at: '2026-01-01T09:00:00Z',
    updated_at: '2026-01-01T13:00:00Z',
    total_quantity_accounted: 1,
    unaccounted_quantity: 0,
    ...overrides,
  } as ProductionRunItem
}

function makeRun(overrides: Partial<ProductionRunDetail> = {}): ProductionRunDetail {
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
    total_items_planned: 1,
    total_items_successful: 1,
    total_items_failed: 0,
    total_material_cost: '0',
    total_estimated_cost: '0',
    ...overrides,
  } as ProductionRunDetail
}

function renderTable() {
  return render(<ProductionHistoryTable productId="product-1" modelIds={[MODEL_ID]} />)
}

describe('ProductionHistoryTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('the estimated cost', () => {
    it('sums two decimal strings instead of concatenating them', async () => {
      // The defect, exactly: `0 + "12.50" + "8.00"` is "012.508.00". Summed
      // as exact decimals it is £20.50.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            items: [
              makeItem({ id: 'a', estimated_total_cost: '12.50' }),
              makeItem({ id: 'b', estimated_total_cost: '8.00' }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.getByText('£20.50')).toBeInTheDocument()
      expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
      expect(screen.queryByText(/012\.508/)).not.toBeInTheDocument()
    })

    it('adds amounts a float would get wrong', async () => {
      // 0.1 + 0.2 in doubles is 0.30000000000000004. Three of these summed
      // exactly is £0.30, and two decimal places of a double would show it
      // only because of the rounding, not because the arithmetic was right.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            items: [
              makeItem({ id: 'a', estimated_total_cost: '0.1' }),
              makeItem({ id: 'b', estimated_total_cost: '0.2' }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.getByText('£0.30')).toBeInTheDocument()
    })

    it('shows a dash where no item carries an estimate', async () => {
      // An uncosted run and a free one are different facts (FR-019).
      mockListProductionRuns.mockResolvedValue({
        runs: [makeRun({ items: [makeItem({ estimated_total_cost: null })] })],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.queryByText('£0.00')).not.toBeInTheDocument()
    })
  })

  describe('the actual cost', () => {
    it('renders the recorded actual, not an estimate scaled by a variance', async () => {
      // The figure the service wrote: £4.00 a unit over 3 successful units is
      // £12.00. The old code would have reported
      // 20.00 * (1 + 50/100) * (3/4 * 100 / 100) = £22.50 -- a number nobody
      // recorded, from a *weight* variance and a yield.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            variance_percentage: 50,
            items: [
              makeItem({
                quantity: 4,
                successful_quantity: 3,
                failed_quantity: 1,
                estimated_total_cost: '20.00',
                actual_cost_per_unit: '4.0000',
              }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.getByText('£12.00')).toBeInTheDocument()
      expect(screen.queryByText('£22.50')).not.toBeInTheDocument()
    })

    it('multiplies a per-unit actual by the quantity exactly', async () => {
      // 0.0215 a unit over 200 units is £4.30. Through a double the per-unit
      // figure is slightly off and the product drifts with it.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            items: [
              makeItem({
                quantity: 200,
                successful_quantity: 200,
                actual_cost_per_unit: '0.0215',
              }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.getByText('£4.30')).toBeInTheDocument()
    })

    it('shows a dash when the run recorded no actual', async () => {
      // The whole point of T193: the old code always produced a figure here,
      // because it derived one from the estimate rather than reading a record.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            status: 'in_progress',
            variance_percentage: 10,
            items: [
              makeItem({ estimated_total_cost: '15.00', actual_cost_per_unit: null }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.getByText('£15.00')).toBeInTheDocument()
      expect(
        screen.getByTitle('No actual cost recorded for this run'),
      ).toBeInTheDocument()
    })
  })

  describe('the cost variance tile', () => {
    it('compares the recorded actual against the estimate', async () => {
      // £22.00 actual against £20.00 estimated is +10.0%.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            items: [
              makeItem({
                quantity: 2,
                successful_quantity: 2,
                estimated_total_cost: '20.00',
                actual_cost_per_unit: '11.00',
              }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('Cost Variance')).toBeInTheDocument()
      })
      expect(screen.getByText(/\+?10\.0%/)).toBeInTheDocument()
    })

    it('is a dash, not 0%, when nothing has recorded an actual', async () => {
      // 0% reads as "on plan" about a comparison that was never made.
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            items: [
              makeItem({ estimated_total_cost: '20.00', actual_cost_per_unit: null }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('Cost Variance')).toBeInTheDocument()
      })
      expect(
        screen.getByTitle('No run has recorded actual costs yet'),
      ).toBeInTheDocument()
      expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
      expect(screen.queryByText('+0.0%')).not.toBeInTheDocument()
    })
  })

  describe('which runs are counted', () => {
    it('ignores items for other products models', async () => {
      mockListProductionRuns.mockResolvedValue({
        runs: [
          makeRun({
            items: [
              makeItem({ id: 'mine', estimated_total_cost: '5.00' }),
              makeItem({
                id: 'theirs',
                model_id: 'someone-elses-model',
                estimated_total_cost: '500.00',
              }),
            ],
          }),
        ],
        total: 1,
        skip: 0,
        limit: 500,
      })

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('RUN-0001')).toBeInTheDocument()
      })
      expect(screen.getByText('£5.00')).toBeInTheDocument()
      expect(screen.queryByText('£505.00')).not.toBeInTheDocument()
    })

    it('says so plainly when the product has no models', async () => {
      mockListProductionRuns.mockResolvedValue({ runs: [], total: 0, skip: 0, limit: 500 })

      render(<ProductionHistoryTable productId="product-1" modelIds={[]} />)

      await waitFor(() => {
        expect(screen.getByText('No production runs found')).toBeInTheDocument()
      })
      expect(screen.getByText('This product has no models assigned')).toBeInTheDocument()
    })
  })
})
