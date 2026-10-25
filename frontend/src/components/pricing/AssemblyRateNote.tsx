/**
 * What an assembly minute is costed at, as the engine costs it (task T275).
 *
 * The product form and the wizard said "@ £10/hr", the rate Tier 0 removed
 * from the engine. Assembly is priced at the pricing policy's handling labour
 * rate (`assembly_minutes / 60 * print_labor_rate` in `costing.py`), so the
 * note names that rate, in the books currency, or no figure at all while the
 * policy is unknown -- never a number the engine does not use (FR-002,
 * Constitution IV).
 */

import { useCurrency } from '@/hooks/useCurrency'
import { usePricingPolicy } from '@/hooks/usePricing'
import { formatMoney } from '@/lib/money'

export function AssemblyRateNote() {
  const { policy } = usePricingPolicy()
  const { currency } = useCurrency()
  const rate = policy?.print_labor_rate

  return (
    <span data-testid="assembly-rate-note">
      Time to assemble and package, costed at your handling labour rate
      {rate ? ` (${formatMoney(rate, currency.symbol)}/hr)` : ''}
    </span>
  )
}
