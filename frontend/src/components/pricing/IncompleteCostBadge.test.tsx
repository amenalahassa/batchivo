/**
 * The badge is the only thing standing between an operator and a cost that
 * looks finished but is not, on the screen where they pick a product. So the
 * two cases that matter are "it appears when there is a reason" and "it stays
 * out of the way when there is not" -- a badge shown on every row would be
 * read as decoration and stop carrying the warning at all (FR-019).
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { IncompleteCostBadge } from './IncompleteCostBadge'

describe('IncompleteCostBadge', () => {
  describe('nothing to report', () => {
    it('renders nothing for an empty list', () => {
      render(<IncompleteCostBadge reasons={[]} />)
      expect(screen.queryByTestId('incomplete-cost-badge')).not.toBeInTheDocument()
    })

    it('renders nothing for null', () => {
      render(<IncompleteCostBadge reasons={null} />)
      expect(screen.queryByTestId('incomplete-cost-badge')).not.toBeInTheDocument()
    })

    it('renders nothing when the API sent no flag at all', () => {
      render(<IncompleteCostBadge reasons={undefined} />)
      expect(screen.queryByTestId('incomplete-cost-badge')).not.toBeInTheDocument()
    })
  })

  describe('something to report', () => {
    it('shows the badge for one reason', () => {
      render(<IncompleteCostBadge reasons={['no print time is recorded']} />)
      expect(screen.getByTestId('incomplete-cost-badge')).toBeInTheDocument()
    })

    it('announces itself as an alert', () => {
      render(<IncompleteCostBadge reasons={['no machine rate is configured']} />)
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    it('carries every reason in the accessible name, not only the tooltip', () => {
      // A tooltip is hover-only on a pointer device and absent to a reader
      // that never focuses the badge, so the reasons go on the trigger too.
      render(
        <IncompleteCostBadge
          reasons={['no print time is recorded', 'no machine rate is configured']}
        />,
      )

      const badge = screen.getByTestId('incomplete-cost-badge')
      expect(badge).toHaveAttribute(
        'aria-label',
        'Incompletely costed: no print time is recorded; no machine rate is configured',
      )
    })

    it('does not claim to be a cost', () => {
      render(<IncompleteCostBadge reasons={['no print time is recorded']} />)
      expect(screen.getByText('Incomplete')).toBeInTheDocument()
    })
  })
})
