/**
 * FeeRuleEditor tests.
 *
 * The behaviour worth testing here is the editor's refusal to let an operator
 * type a figure the backend will reject, and its insistence on saying what a
 * basis means for their money:
 *
 * * **A rate is disabled on a count basis.** A percentage of a quantity is not
 *   an amount, and the API returns `422` for one. Disabling the field means
 *   the operator never submits it.
 * * **Each basis states its consequence.** "Item + shipping" is jargon; "moves
 *   with the item price and the shipping you charge" is the fact that decides
 *   whether the operator picks it.
 * * **Closing is offered beside deleting.** A rule the channel stopped
 *   charging should be closed, because deleting it makes a past order's fees
 *   unreproducible.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@/test/test-utils'
import userEvent from '@testing-library/user-event'
import { FeeRuleEditor } from './FeeRuleEditor'
import type { FeeRule } from '@/types/pricing'

const listMock = vi.fn()
const createMock = vi.fn()
const updateMock = vi.fn()
const removeMock = vi.fn()

vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: {
    list: (...args: unknown[]) => listMock(...args),
    create: (...args: unknown[]) => createMock(...args),
    update: (...args: unknown[]) => updateMock(...args),
    remove: (...args: unknown[]) => removeMock(...args),
  },
}))

const CHANNEL_ID = 'channel-1'

function rule(overrides: Partial<FeeRule> = {}): FeeRule {
  return {
    id: 'rule-1',
    tenant_id: 'tenant-1',
    sales_channel_id: CHANNEL_ID,
    name: 'transaction',
    basis: 'item_plus_shipping',
    rate_pct: '6.5000',
    fixed_amount: '0.00',
    min_amount: null,
    max_amount: null,
    incidence_pct: null,
    sort_order: 10,
    applies_from: '2024-01-01',
    applies_to: null,
    ...overrides,
  }
}

beforeEach(() => {
  listMock.mockReset()
  createMock.mockReset()
  updateMock.mockReset()
  removeMock.mockReset()
  listMock.mockResolvedValue({ rules: [rule()], total: 1, as_of: '2026-06-01' })
  createMock.mockResolvedValue(rule({ id: 'rule-2', name: 'payment_processing' }))
  updateMock.mockResolvedValue(rule({ applies_to: '2026-06-01' }))
  removeMock.mockResolvedValue(undefined)
})

describe('FeeRuleEditor', () => {
  describe('showing the stack', () => {
    it('lists each rule with the basis it is charged on', async () => {
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const row = await screen.findByTestId('fee-rule-transaction')
      expect(within(row).getByText('Item + shipping')).toBeInTheDocument()
    })

    it('says what the basis means for the operator money', async () => {
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const row = await screen.findByTestId('fee-rule-transaction')
      expect(row).toHaveTextContent(/moves with the item price and the shipping you charge/)
    })

    it('shows a cap beside the rule it caps', async () => {
      listMock.mockResolvedValue({
        rules: [rule({ max_amount: '5.00' })],
        total: 1,
        as_of: '2026-06-01',
      })
      render(<FeeRuleEditor channelId={CHANNEL_ID} currencySymbol="$" />)

      const row = await screen.findByTestId('fee-rule-transaction')
      expect(row).toHaveTextContent('capped at $5.00')
    })

    it('labels a rule with an incidence as covering a share of orders', async () => {
      listMock.mockResolvedValue({
        rules: [rule({ incidence_pct: '20.0000' })],
        total: 1,
        as_of: '2026-06-01',
      })
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const row = await screen.findByTestId('fee-rule-transaction')
      expect(row).toHaveTextContent('20% of orders')
    })

    it('shows no rate for a count basis, where a rate has no meaning', async () => {
      listMock.mockResolvedValue({
        rules: [rule({ name: 'handling', basis: 'per_order', rate_pct: '0' })],
        total: 1,
        as_of: '2026-06-01',
      })
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const row = await screen.findByTestId('fee-rule-handling')
      expect(within(row).queryByText(/%/)).not.toBeInTheDocument()
    })

    it('warns that a channel with no rules is costed as charging nothing', async () => {
      listMock.mockResolvedValue({ rules: [], total: 0, as_of: '2026-06-01' })
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const empty = await screen.findByTestId('fee-rule-empty')
      expect(empty).toHaveTextContent(/costed as charging nothing/)
    })
  })

  describe('adding a rule', () => {
    it('disables the rate field on a count basis', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))
      expect(screen.getByLabelText('Rate (%)')).toBeEnabled()

      // The Select is a Radix trigger; switching basis through the draft state
      // is what matters, so drive it through the trigger's own listbox.
      await user.click(screen.getByLabelText('Charged on'))
      await user.click(await screen.findByRole('option', { name: 'Per order' }))

      await waitFor(() => expect(screen.getByLabelText('Rate (%)')).toBeDisabled())
    })

    it('explains why a rate is disabled rather than just greying it out', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))
      await user.click(screen.getByLabelText('Charged on'))
      await user.click(await screen.findByRole('option', { name: 'Per unit sold' }))

      await waitFor(() =>
        expect(
          screen.getByText(/a percentage of a count is not an amount/),
        ).toBeInTheDocument(),
      )
    })

    it('cannot be saved without a name', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))

      expect(screen.getByTestId('fee-rule-save')).toBeDisabled()
    })

    it('sends the rule the operator typed', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))
      await user.type(screen.getByLabelText('Name'), 'payment_processing')
      await user.type(screen.getByLabelText('Rate (%)'), '3')
      await user.type(screen.getByLabelText('Fixed amount'), '0.30')
      await user.click(screen.getByTestId('fee-rule-save'))

      await waitFor(() => expect(createMock).toHaveBeenCalled())
      const [, payload] = createMock.mock.calls[0]
      // A number input normalises its own trailing zeros, so "0.30" arrives
      // as "0.3". Both parse to the same Decimal on the backend, which is why
      // the string is passed through untouched rather than reformatted here --
      // reformatting is where a money string would get parsed into a float.
      expect(payload).toMatchObject({
        name: 'payment_processing',
        basis: 'item_plus_shipping',
        rate_pct: '3',
        fixed_amount: '0.3',
      })
    })

    it('omits the rate entirely on a count basis rather than sending zero', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))
      await user.type(screen.getByLabelText('Name'), 'handling')
      await user.click(screen.getByLabelText('Charged on'))
      await user.click(await screen.findByRole('option', { name: 'Per order' }))
      await user.type(screen.getByLabelText('Fixed amount'), '2.00')
      await user.click(screen.getByTestId('fee-rule-save'))

      await waitFor(() => expect(createMock).toHaveBeenCalled())
      const [, payload] = createMock.mock.calls[0]
      expect(payload).not.toHaveProperty('rate_pct')
      expect(payload).toMatchObject({ basis: 'per_order', fixed_amount: '2' })
    })

    it('leaves the optional clamps out when they are blank', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))
      await user.type(screen.getByLabelText('Name'), 'transaction')
      await user.click(screen.getByTestId('fee-rule-save'))

      await waitFor(() => expect(createMock).toHaveBeenCalled())
      const [, payload] = createMock.mock.calls[0]
      expect(payload).not.toHaveProperty('min_amount')
      expect(payload).not.toHaveProperty('max_amount')
      expect(payload).not.toHaveProperty('incidence_pct')
    })

    it('surfaces the API refusal rather than failing silently', async () => {
      const user = userEvent.setup()
      createMock.mockRejectedValue(
        new Error('min_amount 10.00 exceeds max_amount 5.00'),
      )
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-add'))
      await user.type(screen.getByLabelText('Name'), 'capped')
      await user.click(screen.getByTestId('fee-rule-save'))

      const error = await screen.findByTestId('fee-rule-save-error')
      expect(error).toHaveTextContent(/exceeds max_amount/)
    })
  })

  describe('closing and deleting', () => {
    it('closes a rule with an end date rather than deleting it', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-close-transaction'))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      const [, ruleId, data] = updateMock.mock.calls[0]
      expect(ruleId).toBe('rule-1')
      expect(data).toHaveProperty('applies_to')
      expect(removeMock).not.toHaveBeenCalled()
    })

    it('offers no close on a rule that is already closed', async () => {
      listMock.mockResolvedValue({
        rules: [rule({ applies_to: '2025-12-31' })],
        total: 1,
        as_of: '2026-06-01',
      })
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await screen.findByTestId('fee-rule-transaction')
      expect(screen.queryByTestId('fee-rule-close-transaction')).not.toBeInTheDocument()
    })

    it('marks a closed rule as closed, with the date', async () => {
      listMock.mockResolvedValue({
        rules: [rule({ applies_to: '2025-12-31' })],
        total: 1,
        as_of: '2026-06-01',
      })
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const row = await screen.findByTestId('fee-rule-transaction')
      expect(row).toHaveTextContent('Closed 2025-12-31')
    })

    it('deletes a rule when asked', async () => {
      const user = userEvent.setup()
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      await user.click(await screen.findByTestId('fee-rule-delete-transaction'))

      await waitFor(() => expect(removeMock).toHaveBeenCalledWith(CHANNEL_ID, 'rule-1'))
    })
  })

  describe('permissions', () => {
    it('shows the stack read-only without edit rights (FR-007a)', async () => {
      render(<FeeRuleEditor channelId={CHANNEL_ID} canEdit={false} />)

      await screen.findByTestId('fee-rule-transaction')
      expect(screen.queryByTestId('fee-rule-add')).not.toBeInTheDocument()
      expect(screen.queryByTestId('fee-rule-close-transaction')).not.toBeInTheDocument()
      expect(screen.queryByTestId('fee-rule-delete-transaction')).not.toBeInTheDocument()
    })
  })

  describe('when the rules cannot be loaded', () => {
    it('warns that the margin may be missing fees', async () => {
      listMock.mockRejectedValue(new Error('network'))
      render(<FeeRuleEditor channelId={CHANNEL_ID} />)

      const error = await screen.findByTestId('fee-rule-error')
      expect(error).toHaveTextContent(/may be missing fees/)
    })
  })
})
