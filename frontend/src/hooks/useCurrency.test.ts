/**
 * `useCurrency().formatCurrency` is the money renderer most of the app reaches
 * for, so it has to be the same renderer the pricing screens use.
 *
 * It used to be `parseFloat(value).toFixed(2)` behind the tenant symbol, which
 * differs from `formatMoney` in two ways that both show up on screen:
 *
 * - **Rounding.** An exact decimal string put through a binary double can land
 *   a cent away from the exact value. The product list used this hook while
 *   the product detail page used `formatMoney`, so the two screens SC-008
 *   compares could disagree about one product's make cost.
 * - **A missing amount.** It returned `£0.00`. An unknown cost and a free one
 *   are different facts, and showing the second for the first is the defect
 *   FR-019 exists to prevent.
 *
 * These tests pin the delegation rather than the arithmetic: `formatMoney` has
 * its own tests, and what matters here is that this hook does not have a
 * second opinion (FR-047/FR-019, SC-008, US1/AC2).
 */

import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'

import { useCurrency } from './useCurrency'
import { formatMoney } from '@/lib/money'

/** No AuthProvider here on purpose: the hook falls back to GBP and '£'. */
function format(value: Parameters<ReturnType<typeof useCurrency>['formatCurrency']>[0]) {
  const { result } = renderHook(() => useCurrency())
  return result.current.formatCurrency(value)
}

describe('useCurrency().formatCurrency', () => {
  describe('a missing amount is not a zero', () => {
    it('renders a dash for null', () => {
      expect(format(null)).toBe('—')
    })

    it('renders a dash for undefined', () => {
      expect(format(undefined)).toBe('—')
    })

    it('renders a dash for an empty string', () => {
      expect(format('')).toBe('—')
    })

    it('renders a free item as zero, not as a dash', () => {
      // The distinction the dash exists for: this one really is £0.00.
      expect(format('0')).toBe('£0.00')
    })
  })

  describe('rounding happens in string space', () => {
    it.each([
      ['2.145', '£2.15'],
      ['0.125', '£0.13'],
      ['1.005', '£1.01'],
      ['10.999', '£11.00'],
    ])('renders %s as %s', (amount, expected) => {
      expect(format(amount)).toBe(expected)
    })

    it('agrees with formatMoney on a long decimal the engine can produce', () => {
      const amount = '0.023986666'
      expect(format(amount)).toBe(formatMoney(amount, '£'))
    })
  })

  describe('it is the same renderer the pricing screens use', () => {
    it.each(['12.34', '0.00', '-4.50', '1234.567', ''])(
      'matches formatMoney for %s',
      (amount) => {
        expect(format(amount)).toBe(formatMoney(amount, '£'))
      },
    )
  })

  describe('numbers are still accepted', () => {
    it('formats a number for the callers that pass one', () => {
      expect(format(12.5)).toBe('£12.50')
    })

    it('formats zero as zero rather than a dash', () => {
      expect(format(0)).toBe('£0.00')
    })
  })

  it('exposes the tenant currency config', () => {
    const { result } = renderHook(() => useCurrency())
    expect(result.current.currency).toEqual({ code: 'GBP', symbol: '£' })
  })
})
