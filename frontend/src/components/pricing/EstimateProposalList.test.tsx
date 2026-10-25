/**
 * Accepting a proposal sets a figure's origin to observed and moves a price,
 * so this component's three paths are the cases Constitution II names: the
 * success path, the reject path, and the error path.
 *
 * It was the only component in `src/components/pricing/` with no test file,
 * reached by `reachability.test.ts` alone -- which asserts it is imported and
 * nothing about what it does.
 *
 * Two of its claims are load-bearing and are asserted here as text, because
 * they are the difference between a reviewer approving a change and a reviewer
 * undoing one:
 *
 * - **FR-042e**: pricing still uses the current figure; nothing has moved yet.
 * - **FR-042d**: rejecting is not a veto on the field -- a new outcome can
 *   raise it again. An operator who believes "reject" silences the figure for
 *   ever will accept a bad reading rather than lose the alert.
 *
 * And the whole-or-nothing rule (FR-042c): there is no partial acceptance, so
 * the row offers exactly two decisions.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { render } from '@/test/test-utils'
import { EstimateProposalList } from './EstimateProposalList'
import {
  acceptEstimateRevision,
  listEstimateRevisions,
  rejectEstimateRevision,
} from '@/lib/api/pricing'
import type { EstimateRevision, EstimateRevisionList } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  listEstimateRevisions: vi.fn(),
  acceptEstimateRevision: vi.fn(),
  rejectEstimateRevision: vi.fn(),
}))

const mockList = listEstimateRevisions as Mock
const mockAccept = acceptEstimateRevision as Mock
const mockReject = rejectEstimateRevision as Mock

function makeRevision(overrides: Partial<EstimateRevision> = {}): EstimateRevision {
  return {
    id: 'revision-1',
    entity_type: 'model',
    entity_id: 'model-1',
    field_name: 'print_time_minutes',
    current_value: '100.0000',
    observed_value: '910.0000',
    divergence_pct: '810.0000',
    derived_from_run_ids: ['run-a', 'run-b'],
    state: 'pending',
    observed_as_of: '2026-02-01',
    reviewed_by_user_id: null,
    reviewed_at: null,
    created_at: '2026-02-01T10:00:00Z',
    ...overrides,
  }
}

function listOf(...revisions: EstimateRevision[]): EstimateRevisionList {
  return { revisions, total: revisions.length, pending_count: revisions.length }
}

describe('EstimateProposalList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('what the screen says about a proposal', () => {
    it('shows the estimate, the observation and the gap', async () => {
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      // "100 → 910" is the fact; "810.0% out" is the judgement that makes it
      // reviewable (FR-042c). Trailing zeros from the column scale are gone.
      expect(screen.getByTestId('proposal-current')).toHaveTextContent('100')
      expect(screen.getByTestId('proposal-observed')).toHaveTextContent('910')
      expect(screen.getByTestId('proposal-divergence')).toHaveTextContent('810.0% out')
    })

    it('says how far to believe the observation (T259)', async () => {
      mockList.mockResolvedValue(listOf(makeRevision({ confidence: '0.3680' })))

      render(<EstimateProposalList />)

      expect(await screen.findByTestId('proposal-confidence')).toHaveTextContent(
        '37% confidence',
      )
    })

    it('keeps the exact divergence available, not only the rounded one', async () => {
      mockList.mockResolvedValue(listOf(makeRevision({ divergence_pct: '810.3647' })))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-divergence')).toHaveTextContent('810.4% out')
      })
      expect(screen.getByTestId('proposal-divergence')).toHaveAttribute(
        'title',
        'Exactly 810.3647% when this was raised',
      )
    })

    it('says pricing has not moved yet', async () => {
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByText(/Nothing changes until you accept/)).toBeInTheDocument()
      })
      expect(screen.getByText(/Pricing still uses 100/)).toBeInTheDocument()
    })

    it('lists the outcomes it came from, so a reviewer can check them', async () => {
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-outcomes')).toBeInTheDocument()
      })
      expect(screen.getByText('run-a')).toBeInTheDocument()
      expect(screen.getByText('run-b')).toBeInTheDocument()
      expect(screen.getByText(/From 2 recorded outcomes/)).toBeInTheDocument()
    })

    it('offers exactly two decisions, because a proposal is taken whole', async () => {
      // FR-042c: no partial acceptance. Half a proposal would produce a figure
      // no evidence supports.
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      expect(
        screen.getByRole('button', { name: /Accept the observed print time minutes/ }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Reject the observed print time minutes/ }),
      ).toBeInTheDocument()
    })
  })

  describe('nothing waiting', () => {
    it('says so, and explains that agreeing figures update themselves', async () => {
      mockList.mockResolvedValue(listOf())

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('no-proposals')).toBeInTheDocument()
      })
      expect(screen.queryByTestId('proposal-count')).not.toBeInTheDocument()
    })
  })

  describe('accepting', () => {
    it('sends the acceptance for that proposal', async () => {
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))
      mockAccept.mockResolvedValue(makeRevision({ state: 'accepted' }))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Accept the observed print time minutes/ }),
      )

      await waitFor(() => {
        expect(mockAccept).toHaveBeenCalledWith('revision-1')
      })
      // Accepting is the decision itself -- no confirmation stands between the
      // operator and the figure they came here to approve.
      expect(mockReject).not.toHaveBeenCalled()
    })

    it('reports a failure and says the figure is unchanged', async () => {
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))
      mockAccept.mockRejectedValue(new Error('network'))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Accept the observed print time minutes/ }),
      )

      await waitFor(() => {
        expect(screen.getByTestId('proposal-error')).toBeInTheDocument()
      })
      expect(screen.getByTestId('proposal-error')).toHaveTextContent(/figure is unchanged/)
    })
  })

  describe('rejecting', () => {
    it('confirms first, and does not send anything until confirmed', async () => {
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Reject the observed print time minutes/ }),
      )

      await waitFor(() => {
        expect(screen.getByText('Keep the current figure?')).toBeInTheDocument()
      })
      expect(mockReject).not.toHaveBeenCalled()
    })

    it('says plainly that the alert is not being switched off', async () => {
      // FR-042d. This sentence is why the confirmation exists at all.
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Reject the observed print time minutes/ }),
      )

      await waitFor(() => {
        expect(
          screen.getByText(/a new recorded outcome can raise it afresh/),
        ).toBeInTheDocument()
      })
      expect(screen.getByText(/you are not switching\s+the alert off/)).toBeInTheDocument()
    })

    it('sends the rejection once confirmed', async () => {
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))
      mockReject.mockResolvedValue(makeRevision({ state: 'rejected' }))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Reject the observed print time minutes/ }),
      )
      await waitFor(() => {
        expect(screen.getByText('Keep the current figure?')).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: 'Keep the current figure' }))

      await waitFor(() => {
        expect(mockReject).toHaveBeenCalledWith('revision-1')
      })
      expect(mockAccept).not.toHaveBeenCalled()
    })

    it('sends nothing when the confirmation is cancelled', async () => {
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Reject the observed print time minutes/ }),
      )
      await waitFor(() => {
        expect(screen.getByText('Keep the current figure?')).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: 'Cancel' }))

      await waitFor(() => {
        expect(screen.queryByText('Keep the current figure?')).not.toBeInTheDocument()
      })
      expect(mockReject).not.toHaveBeenCalled()
    })

    it('reports a failed rejection and says the figure is unchanged', async () => {
      const user = userEvent.setup({ delay: null })
      mockList.mockResolvedValue(listOf(makeRevision()))
      mockReject.mockRejectedValue(new Error('network'))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('proposal-revision-1')).toBeInTheDocument()
      })

      await user.click(
        screen.getByRole('button', { name: /Reject the observed print time minutes/ }),
      )
      await waitFor(() => {
        expect(screen.getByText('Keep the current figure?')).toBeInTheDocument()
      })
      await user.click(screen.getByRole('button', { name: 'Keep the current figure' }))

      await waitFor(() => {
        expect(screen.getByTestId('proposal-error')).toBeInTheDocument()
      })
    })
  })

  describe('the list itself fails to load', () => {
    it('says the figures are unchanged rather than showing an empty review list', async () => {
      // An empty list and an unreachable one look the same and mean opposite
      // things: one says nothing needs review, the other says we do not know.
      mockList.mockRejectedValue(new Error('network'))

      render(<EstimateProposalList />)

      await waitFor(() => {
        expect(screen.getByTestId('estimate-proposals-error')).toBeInTheDocument()
      })
      expect(screen.getByRole('alert')).toHaveTextContent(/Your figures are unchanged/)
      expect(screen.queryByTestId('no-proposals')).not.toBeInTheDocument()
    })
  })

  describe('scoping', () => {
    it('asks only for pending proposals, narrowed to the record when given one', async () => {
      mockList.mockResolvedValue(listOf())

      render(<EstimateProposalList entityType="model" entityId="model-7" />)

      await waitFor(() => {
        expect(mockList).toHaveBeenCalledWith({
          state: 'pending',
          entityType: 'model',
          entityId: 'model-7',
        })
      })
    })
  })
})
