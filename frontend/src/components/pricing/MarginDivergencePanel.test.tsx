/**
 * The in-app half of the FR-042 alert.
 *
 * The operator sets `margin_alert_threshold_pct` on the pricing-policy screen
 * and, before this panel, heard nothing: the sweep wrote a warning into a
 * worker's log and no client called `GET /reconciliation/margin-divergence`.
 *
 * What is asserted here is what US7 scenario 3 asks for -- that the operator
 * is told **which lines moved**, not merely that a product underperformed --
 * and the two ways this screen can mislead: reporting an undefined margin as
 * 0%, and reading as though something has already been changed.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { render } from '@/test/test-utils'
import { MarginDivergencePanel } from './MarginDivergencePanel'
import { feeRulesApi } from '@/lib/api/feeRules'
import type { MarginDivergence, MarginDivergenceList } from '@/types/pricing'

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: { getMarginDivergence: vi.fn() },
}))

const mockGet = feeRulesApi.getMarginDivergence as Mock

function makeDivergence(overrides: Partial<MarginDivergence> = {}): MarginDivergence {
  return {
    order_id: 'order-1',
    order_item_id: 'item-1',
    product_id: 'product-1',
    product_name: 'Articulated Dragon',
    sold_on: '2026-02-01',
    margin_basis: 'net_revenue',
    planned_margin_pct: '35.2693',
    realised_margin_pct: '22.1040',
    divergence_points: '-13.1653',
    threshold_points: '5.0000',
    diverges: true,
    shortfall: true,
    planned_profit: '8.40',
    realised_profit: '5.18',
    movements: [
      { key: 'fees', planned: '1.20', realised: '3.00', delta: '1.80' },
      { key: 'material', planned: '2.10', realised: '2.52', delta: '0.42' },
    ],
    ...overrides,
  }
}

function listOf(...divergences: MarginDivergence[]): MarginDivergenceList {
  return {
    divergences,
    total: divergences.length,
    alerting: divergences.length,
    threshold_points: '5.0000',
  }
}

describe('MarginDivergencePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('which lines moved', () => {
    it('names each moved line with its planned and realised figure', async () => {
      // US7 scenario 3. "fees +1.80" is a decision the operator can make this
      // afternoon; "this product underperformed" is three screens of hunting.
      mockGet.mockResolvedValue(listOf(makeDivergence()))

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByTestId('divergence-movements')).toBeInTheDocument()
      })

      expect(screen.getByText('fees')).toBeInTheDocument()
      expect(screen.getByText('material')).toBeInTheDocument()
      expect(screen.getByText('£1.20 → £3.00')).toBeInTheDocument()
      expect(screen.getByText('+£1.80')).toBeInTheDocument()
      expect(screen.getByText('+£0.42')).toBeInTheDocument()
    })

    it('says so when no cost line moved, rather than showing an empty list', async () => {
      mockGet.mockResolvedValue(listOf(makeDivergence({ movements: [] })))

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByTestId('divergence-no-movements')).toBeInTheDocument()
      })
      expect(screen.getByText(/check the revenue on this order/)).toBeInTheDocument()
    })
  })

  describe('the two percentages', () => {
    it('shows both, with the basis they are on', async () => {
      mockGet.mockResolvedValue(listOf(makeDivergence()))

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByTestId('divergence-planned')).toBeInTheDocument()
      })

      expect(screen.getByTestId('divergence-planned')).toHaveTextContent('35.3%')
      expect(screen.getByTestId('divergence-realised')).toHaveTextContent('22.1%')
      expect(screen.getByTestId('divergence-points')).toHaveTextContent('-13.2 points')
      // FR-031b: a margin means nothing without the basis it was taken on.
      expect(screen.getByText(/net revenue/)).toBeInTheDocument()
    })

    it('shows a dash for an undefined margin, never 0%', async () => {
      // Where fees consumed the whole basis there is no margin to report, and
      // "0%" reads as break-even on a sale that lost money.
      mockGet.mockResolvedValue(
        listOf(
          makeDivergence({
            realised_margin_pct: null,
            divergence_points: null,
          }),
        ),
      )

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByTestId('divergence-realised')).toBeInTheDocument()
      })

      expect(screen.getByTestId('divergence-realised')).toHaveTextContent('—')
      expect(screen.getByTestId('divergence-realised')).not.toHaveTextContent('0.0%')
    })
  })

  describe('it does not read as a correction', () => {
    it('says nothing has been changed', async () => {
      mockGet.mockResolvedValue(listOf(makeDivergence()))

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(
          screen.getByText(/no price moved and no estimate was revised/),
        ).toBeInTheDocument()
      })
    })

    it('names the operator threshold these were measured against', async () => {
      mockGet.mockResolvedValue(listOf(makeDivergence()))

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByText(/your threshold of 5.0 points/)).toBeInTheDocument()
      })
    })
  })

  describe('nothing diverged', () => {
    it('says every line came in within the threshold', async () => {
      mockGet.mockResolvedValue(listOf())

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByTestId('no-divergences')).toBeInTheDocument()
      })
      expect(screen.queryByTestId('divergence-count')).not.toBeInTheDocument()
    })
  })

  describe('the list fails to load', () => {
    it('says so rather than showing an all-clear', async () => {
      // An unreachable list and an empty one mean opposite things.
      mockGet.mockRejectedValue(new Error('network'))

      render(<MarginDivergencePanel />)

      await waitFor(() => {
        expect(screen.getByTestId('margin-divergence-error')).toBeInTheDocument()
      })
      expect(screen.getByRole('alert')).toHaveTextContent(/Nothing has been changed/)
      expect(screen.queryByTestId('no-divergences')).not.toBeInTheDocument()
    })
  })

  describe('what it asks for', () => {
    it('requests only the lines past the threshold', async () => {
      // A panel that listed every settled line would not be an alert.
      mockGet.mockResolvedValue(listOf())

      render(<MarginDivergencePanel productId="product-9" since="2026-01-01" />)

      await waitFor(() => {
        expect(mockGet).toHaveBeenCalledWith({
          productId: 'product-9',
          since: '2026-01-01',
          onlyAlerting: true,
        })
      })
    })
  })
})
