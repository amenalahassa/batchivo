/**
 * SalesChannelForm tests (task T194).
 *
 * At 465 lines this form carries the whole channel-economics surface --
 * `tax_remitter` (FR-028b), `expected_discount_pct` and `expected_refund_pct`
 * (FR-026), `free_shipping_threshold` and `rounding_rule` (FR-033) and
 * `currency_code` (FR-028) -- and had no test, while the `FeeRuleEditor` the
 * plan names beside it has one.
 *
 * These are the operator decisions FR-002 says no automated process may
 * overwrite, written through a form nothing asserted. A zod default silently
 * flipping `tax_remitter` to `operator`, or a cleared threshold saving as
 * `'0'` rather than `null`, would change a margin with nothing objecting --
 * and both are the kind of defect that produces a wrong number and no error,
 * which this project's own history says is the costly kind (Constitution II).
 *
 * Three paths, the ones the sibling's test covers: load, edit-and-save, and
 * the empty-to-null mapping.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@/test/test-utils'
import userEvent from '@testing-library/user-event'

import { SalesChannelForm } from './SalesChannelForm'
import type { SalesChannel } from '@/lib/api/sales-channels'

const createMock = vi.fn()
const updateMock = vi.fn()
const navigateMock = vi.fn()

vi.mock('@/lib/api/sales-channels', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sales-channels')>()
  return {
    ...actual,
    createSalesChannel: (...args: unknown[]) => createMock(...args),
    updateSalesChannel: (...args: unknown[]) => updateMock(...args),
  }
})

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useNavigate: () => navigateMock }
})

const CHANNEL_ID = 'channel-1'

function channel(overrides: Partial<SalesChannel> = {}): SalesChannel {
  return {
    id: CHANNEL_ID,
    tenant_id: 'tenant-1',
    name: 'Etsy UK',
    platform_type: 'etsy',
    monthly_cost: '12.50',
    is_active: true,
    tax_remitter: 'marketplace',
    expected_discount_pct: '7.5000',
    expected_refund_pct: '2.2500',
    free_shipping_threshold: '35.00',
    rounding_rule: 'psychological_99',
    currency_code: 'USD',
    offsite_ads_opt_in: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as SalesChannel
}

beforeEach(() => {
  createMock.mockReset()
  updateMock.mockReset()
  navigateMock.mockReset()
  createMock.mockResolvedValue(channel())
  updateMock.mockResolvedValue(channel())
})

/** The exact string a numeric field holds, trailing zeros and all. */
function valueOf(label: string): string {
  return (screen.getByLabelText(label) as HTMLInputElement).value
}

/** Replace a controlled numeric field's contents in one event. */
function setValue(label: string, next: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value: next } })
}

/** The payload of the single save this form performed. */
function savedWith(mock: typeof createMock) {
  expect(mock).toHaveBeenCalledTimes(1)
  return mock.mock.calls[0][mock === updateMock ? 1 : 0] as Record<string, unknown>
}

// The role the signed-in user holds; each test starts as an admin (T238).
const auth = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'operator@example.com', role: auth.role }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})
beforeEach(() => {
  auth.role = 'admin'
})

describe('SalesChannelForm', () => {
  describe('loading an existing channel', () => {
    it('shows each economics figure the channel actually carries', async () => {
      // Not the zod defaults. A form that renders `operator` and `GBP` for a
      // marketplace-remitting USD channel is one an operator would "correct"
      // by saving, overwriting their own decision (FR-002).
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK')
      })

      // The exact strings, not the numbers they parse to: "2.2500" and 2.25
      // are one number and two different figures on the wire.
      expect(valueOf('Monthly Cost (£)')).toBe('12.50')
      expect(valueOf('Expected discount (%)')).toBe('7.5000')
      expect(valueOf('Refund reserve (%)')).toBe('2.2500')
      expect(valueOf('Free shipping above')).toBe('35.00')
      expect(screen.getByLabelText('Currency')).toHaveValue('USD')

      // The two selects render their chosen option rather than the default,
      // read off the trigger rather than the hidden native <option> Radix
      // keeps beside it, which carries the same text.
      expect(
        within(screen.getByLabelText('Who remits sales tax')).getByText('The marketplace'),
      ).toBeInTheDocument()
      expect(
        within(screen.getByLabelText('Price rounding')).getByText('End in .99'),
      ).toBeInTheDocument()
    })

    it('renders an unset threshold and rounding rule as empty, not as zero', async () => {
      // `free_shipping_threshold: null` means no free shipping is offered. A
      // zero in the box would mean everything ships free, which is the
      // opposite (FR-033).
      render(
        <SalesChannelForm
          channel={channel({ free_shipping_threshold: null, rounding_rule: null })}
          mode="edit"
        />,
      )

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK')
      })
      expect(valueOf('Free shipping above')).toBe('')
      // The trigger, not the hidden native <option> of the same text.
      expect(
        within(screen.getByLabelText('Price rounding')).getByText('No rounding'),
      ).toBeInTheDocument()
    })

    it('starts a new channel on the documented defaults', async () => {
      render(<SalesChannelForm mode="create" />)

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('')
      })

      expect(screen.getByLabelText('Currency')).toHaveValue('GBP')
      expect(valueOf('Expected discount (%)')).toBe('0')
      expect(valueOf('Refund reserve (%)')).toBe('0')
      // FR-050: a tenant who changes no setting sees no figure move, so the
      // default remitter is the one the migration gave every channel.
      expect(
        within(screen.getByLabelText('Who remits sales tax')).getByText('You do'),
      ).toBeInTheDocument()
    })
  })

  describe('editing and saving', () => {
    it('sends back every economics figure, unchanged where untouched', async () => {
      // The defect this guards: a save that round-trips a figure through a
      // default and returns a different one than was loaded.
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK')
      })

      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      const saved = savedWith(updateMock)

      expect(saved).toMatchObject({
        name: 'Etsy UK',
        tax_remitter: 'marketplace',
        expected_discount_pct: '7.5000',
        expected_refund_pct: '2.2500',
        free_shipping_threshold: '35.00',
        rounding_rule: 'psychological_99',
        currency_code: 'USD',
        offsite_ads_opt_in: true,
      })
    })

    it('saves an edited reserve as the string the operator typed', async () => {
      // A percentage crosses the wire as a decimal string, so what is typed
      // is what is stored -- no parse, no re-render through a double.
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      await screen.findByLabelText('Refund reserve (%)')
      setValue('Refund reserve (%)', '3.1250')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      expect(savedWith(updateMock).expected_refund_pct).toBe('3.1250')
    })

    it('upper-cases a lower-case currency code', async () => {
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      const currency = await screen.findByLabelText('Currency')
      await user.clear(currency)
      await user.type(currency, 'eur')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      expect(savedWith(updateMock).currency_code).toBe('EUR')
    })

    it('creates a channel through the create path', async () => {
      const user = userEvent.setup()
      render(<SalesChannelForm mode="create" />)

      await user.type(await screen.findByLabelText('Name'), 'Local Craft Fair')
      await user.click(screen.getByRole('button', { name: 'Create Channel' }))

      await waitFor(() => expect(createMock).toHaveBeenCalled())
      expect(savedWith(createMock)).toMatchObject({
        name: 'Local Craft Fair',
        currency_code: 'GBP',
        monthly_cost: '0',
      })
      expect(updateMock).not.toHaveBeenCalled()
    })
  })

  describe('the empty-to-null mapping', () => {
    it('saves a cleared threshold as null, never as zero', async () => {
      // The one that would change a margin silently: a threshold of '0' means
      // every order ships free, so the postage comes out of the operator's
      // margin on all of them (FR-033).
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      await screen.findByLabelText('Free shipping above')
      setValue('Free shipping above', '')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      const saved = savedWith(updateMock)

      expect(saved.free_shipping_threshold).toBeNull()
      expect(saved.free_shipping_threshold).not.toBe('0')
      expect(saved.free_shipping_threshold).not.toBe('')
    })

    it('saves no-rounding as null rather than an empty rule name', async () => {
      const user = userEvent.setup()
      render(
        <SalesChannelForm channel={channel({ rounding_rule: null })} mode="edit" />,
      )

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK')
      })
      expect(
        within(screen.getByLabelText('Price rounding')).getByText('No rounding'),
      ).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      expect(savedWith(updateMock).rounding_rule).toBeNull()
    })

    it('keeps a zero reserve as "0", which is a decision rather than an absence', async () => {
      // Zero here is meaningful and different from the threshold case: a
      // channel that expects no refunds holds no reserve, which is a figure.
      const user = userEvent.setup()
      render(
        <SalesChannelForm
          channel={channel({ expected_refund_pct: '0', expected_discount_pct: '0' })}
          mode="edit"
        />,
      )

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK')
      })
      expect(valueOf('Refund reserve (%)')).toBe('0')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      const saved = savedWith(updateMock)
      expect(saved.expected_refund_pct).toBe('0')
      expect(saved.expected_discount_pct).toBe('0')
    })
  })

  describe('refusing a figure the backend would reject', () => {
    it('does not save a name that is empty', async () => {
      const user = userEvent.setup()
      render(<SalesChannelForm mode="create" />)

      await waitFor(() => {
        expect(screen.getByLabelText('Name')).toHaveValue('')
      })
      await user.click(screen.getByRole('button', { name: 'Create Channel' }))

      await waitFor(() => {
        expect(screen.getByText('Name is required')).toBeInTheDocument()
      })
      expect(createMock).not.toHaveBeenCalled()
    })

    it('does not save a currency code that is not three letters', async () => {
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      const currency = await screen.findByLabelText('Currency')
      await user.clear(currency)
      await user.type(currency, 'US')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => {
        expect(screen.getByText('Use a three-letter currency code')).toBeInTheDocument()
      })
      expect(updateMock).not.toHaveBeenCalled()
    })

    it('does not save a reserve that is not a number', async () => {
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      await screen.findByLabelText('Refund reserve (%)')
      // A number input refuses most of this, so the value is set directly --
      // the point is that zod, not the input type, is what stops the save.
      setValue('Refund reserve (%)', 'a lot')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => {
        expect(screen.getByText('Must be a valid percentage')).toBeInTheDocument()
      })
      expect(updateMock).not.toHaveBeenCalled()
    })
  })

  describe('the precision the operator can actually enter', () => {
    it('saves a four-decimal reserve rather than silently refusing it', async () => {
      // Found by writing this file, and a real defect rather than a test
      // artifact. The inputs carried `step="0.01"`, so the browser's own
      // constraint validation blocked the submit for 3.1250% -- and blocked
      // it *silently*, with no message, because nothing in the form considered
      // the value invalid. The zod rule beside it permits four decimals and
      // the column stores `Numeric(_, 4)`; the fixture's own 2.2500% could be
      // loaded and never re-saved.
      //
      // This is the shape of defect T194 exists to catch: an operator
      // decision that will not save, with nothing objecting.
      const user = userEvent.setup()
      render(<SalesChannelForm channel={channel()} mode="edit" />)

      await screen.findByLabelText('Refund reserve (%)')
      setValue('Refund reserve (%)', '3.1250')
      setValue('Expected discount (%)', '8.3333')
      await user.click(screen.getByRole('button', { name: 'Save Changes' }))

      await waitFor(() => expect(updateMock).toHaveBeenCalled())
      const saved = savedWith(updateMock)
      expect(saved.expected_refund_pct).toBe('3.1250')
      expect(saved.expected_discount_pct).toBe('8.3333')
    })

    it('lets the step through for every decimal the schema allows', async () => {
      // The guard against the step being tightened back to 0.01: each of
      // these is a value the zod rule accepts, so each must reach the API.
      const user = userEvent.setup()

      for (const entered of ['1', '1.5', '1.25', '1.125', '1.1875']) {
        updateMock.mockReset()
        updateMock.mockResolvedValue(channel())
        const { unmount } = render(<SalesChannelForm channel={channel()} mode="edit" />)

        await screen.findByLabelText('Refund reserve (%)')
        setValue('Refund reserve (%)', entered)
        await user.click(screen.getByRole('button', { name: 'Save Changes' }))

        await waitFor(() => expect(updateMock).toHaveBeenCalled())
        expect(savedWith(updateMock).expected_refund_pct).toBe(entered)
        unmount()
      }
    })
  })
})

describe('SalesChannelForm by role', () => {
  it('shows a viewer every control disabled, saying why', async () => {
    auth.role = 'viewer'
    render(<SalesChannelForm channel={channel()} mode="edit" />)

    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK'))
    expect(screen.getByLabelText('Name')).toBeDisabled()
    expect(screen.getByTestId('read-only-notice')).toBeInTheDocument()
  })

  it('lets a member rename the channel but not move its levers', async () => {
    auth.role = 'member'
    render(<SalesChannelForm channel={channel()} mode="edit" />)

    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK'))
    expect(screen.getByLabelText('Name')).toBeEnabled()
    expect(screen.getByLabelText('Monthly Cost (£)')).toBeDisabled()
    expect(screen.getByTestId('channel-levers')).toBeDisabled()
    expect(screen.getByTestId('levers-read-only-notice')).toBeInTheDocument()
  })

  it('lets an admin move the levers', async () => {
    render(<SalesChannelForm channel={channel()} mode="edit" />)

    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Etsy UK'))
    expect(screen.getByLabelText('Monthly Cost (£)')).toBeEnabled()
    expect(screen.queryByTestId('levers-read-only-notice')).not.toBeInTheDocument()
  })
})
