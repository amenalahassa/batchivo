/**
 * Currency Hook
 *
 * Provides currency formatting based on tenant settings.
 * Uses the currency symbol from the authenticated user's tenant.
 */

import { useOptionalAuth } from '@/contexts/AuthContext'
import { formatMoney } from '@/lib/money'
import type { Money } from '@/types/pricing'

interface CurrencyConfig {
  code: string
  symbol: string
}

interface UseCurrencyReturn {
  currency: CurrencyConfig
  formatCurrency: (value: Money | number | null | undefined) => string
}

/**
 * Hook to access tenant currency settings and formatting
 */
export function useCurrency(): UseCurrencyReturn {
  // Optional, because a currency symbol is a display preference. A leaf
  // component showing a cost must not throw because its tree has no
  // `AuthProvider`; without one it falls back to the default below.
  const user = useOptionalAuth()?.user

  const currency: CurrencyConfig = {
    code: user?.currency_code || 'GBP',
    symbol: user?.currency_symbol || '£',
  }

  /**
   * Format an amount as money, in the tenant's currency.
   *
   * This delegates to `formatMoney`, which is the one renderer for money in
   * this app. It used to be `parseFloat(value).toFixed(2)` behind the symbol,
   * which differs from `formatMoney` in two ways that both matter:
   *
   * - **Rounding.** `parseFloat` puts an exact decimal string through a binary
   *   double, so a figure the engine computed exactly could render a cent away
   *   from the same figure on a screen that used `formatMoney` -- and the two
   *   screens SC-008 compares did exactly that for one product's make cost.
   * - **A missing amount.** This returned `£0.00` for one. An unknown cost and
   *   a free one are different facts, and a product with no cost reading as
   *   costing nothing is the defect FR-019 exists to prevent, so a missing
   *   amount is a dash (FR-047/FR-019, SC-008, US1/AC2).
   *
   * `number` is still accepted because callers across the app pass one, but an
   * amount that arrives from the API as a decimal string should stay a string
   * all the way here: converting it to a number first is the precision loss
   * this delegation removes.
   */
  const formatCurrency = (value: Money | number | null | undefined): string =>
    formatMoney(typeof value === 'number' ? String(value) : value, currency.symbol)

  return { currency, formatCurrency }
}
