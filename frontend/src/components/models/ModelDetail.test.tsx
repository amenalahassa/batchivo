/**
 * The model screens report a cost, and derive no price (tasks T146, T151).
 *
 * These are source-level assertions for the same reason the product screens'
 * are: the defects they guard against are *constructs*, not rendered strings.
 * A markup multiplier and a `parseFloat` on a money figure are both invisible
 * in a snapshot — the number looks plausible either way — and both shipped
 * here once already. Reading the file is the only check that fails on the
 * construct rather than on one example of its output.
 *
 * `ProductDetail.test.tsx` holds the same three checks for the product side.
 * The model side needed its own because T140 and T143 stopped at the product
 * directory, which left the model detail screen carrying the markup tiles and
 * the float arithmetic for a further two phases.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { vi, beforeEach, describe, expect, it } from 'vitest'

//: Every model-side screen that shows or edits a cost figure.
const MODEL_SCREENS = ['ModelDetail.tsx', 'ComponentsEditor.tsx', 'BOMEditor.tsx']

function sourceOf(name: string): string {
  return readFileSync(join(__dirname, name), 'utf8')
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

describe('the model screens derive no price of their own', () => {
  it('has no markup multiplier left on the detail page', () => {
    // `totalCost * 2.5` and `totalCost / 0.60` were rendered as "Recommended
    // Price" and "Alternative Price", from markups no operator configured and
    // before any fee, reserve, postage figure or tax. FR-007 is explicit that
    // what a customer will pay is not the system's to compute as a figure.
    const source = sourceOf('ModelDetail.tsx')
    for (const markup of ['* 2.5', '/ 0.60', '* 3.0', '* 3.00']) {
      expect(source).not.toContain(`totalCost ${markup}`)
    }
    expect(source).not.toMatch(/label="Recommended Price"|label="Alternative Price"/)
    expect(source).not.toMatch(/recommendedPrice|marginBasedPrice/)
  })

  it('points the operator at the solver and the ladder instead', () => {
    // Removing the tiles must not leave the screen silent about how a price is
    // actually arrived at (FR-032, FR-007). A model is not priced on a channel,
    // so the pointer names the product screen where it is.
    const source = sourceOf('ModelDetail.tsx')
    expect(source).toContain('Find a price')
    expect(source).toContain('A model carries a cost, not a price')
  })

  it('does not parse a money figure into a float on any of them', () => {
    // What is *parsed* decides this, not what else shares the line. A weight
    // in grams and a duration in hours are legitimately floats — `money.ts`
    // is deliberately only for amounts and rates — and both appear beside a
    // per-gram cost in the same expression.
    const MONEY = /cost|price|profit|margin|fee|revenue|amount|rate_pct|total_cost/i

    for (const name of MODEL_SCREENS) {
      const offenders = sourceOf(name)
        .split('\n')
        .map((line, index) => [index + 1, line] as const)
        // A comment naming the construct is how these files explain why it is
        // gone; only code counts.
        .filter(([, line]) => !/^\s*(\/\/|\*|\/\*)/.test(line))
        .flatMap(([lineNumber, line]) =>
          [...line.matchAll(/parseFloat\s*\(([^)]*)\)/g)]
            .filter((match) => MONEY.test(match[1]))
            .map(() => `${name}:${lineNumber}: ${line.trim()}`),
        )

      expect(
        offenders,
        `${name} turns a money figure into a float; the API sends decimal ` +
          `strings and @/lib/money has exact add, subtract, multiply and ` +
          `divide (Constitution IV)`,
      ).toEqual([])
    }
  })

  it('multiplies a line total exactly rather than in float space', () => {
    // A unit cost times a quantity, and a per-gram cost times a weight, are
    // both lines `costing.py` already owns. Computed here at all they must at
    // least land on the same digits (FR-047, FR-048).
    expect(sourceOf('ComponentsEditor.tsx')).toContain(
      'multiplyMoney(component.unit_cost, component.quantity)',
    )
    expect(sourceOf('BOMEditor.tsx')).toContain(
      'multiplyMoney(material.cost_per_gram, material.weight_grams)',
    )
  })

  it('compares actual against theoretical exactly, so the arrow points the right way', () => {
    // `(actual - theoretical) / theoretical` in float space turns a run that
    // matched plan into a -1.4e-17 overrun, and the variance card's arrow then
    // reports the opposite finding.
    const source = sourceOf('ModelDetail.tsx')
    expect(source).toContain('subtractMoney(actualCost, totalCost)')
    expect(source).not.toMatch(/actualCost - totalCost/)
  })

  it('is reading the real files, so these cannot pass vacuously', () => {
    for (const name of MODEL_SCREENS) {
      expect(sourceOf(name).length).toBeGreaterThan(1000)
    }
    // A control: the construct being banned is one the checker can see, and a
    // weight is not one of the things it bans.
    const MONEY = /cost|price|profit|margin|fee|revenue|amount|rate_pct|total_cost/i
    const parsed = (line: string) =>
      [...line.matchAll(/parseFloat\s*\(([^)]*)\)/g)].filter((m) => MONEY.test(m[1]))
    expect(parsed('formatCurrency(parseFloat(x.unit_cost))')).toHaveLength(1)
    expect(parsed('parseFloat(material.weight_grams).toFixed(2)')).toHaveLength(0)
  })
})

describe('the product wizard sums no make-cost of its own', () => {
  /**
   * The file with its comments taken out.
   *
   * These screens explain a removed defect by naming it in a comment, which is
   * the right place for it and the reason a plain `toContain` on the source
   * would fail on the explanation rather than on the code. Only code counts.
   */
  function wizardSource(): string {
    return readFileSync(join(__dirname, '..', 'products', 'ProductWizard', 'WizardReview.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/.*$/gm, '$1')
  }

  it('no longer costs assembly at a hardcoded labour rate', () => {
    // `(assemblyMinutes / 60) * 10` is the same rate hardcoded to 10.0 that
    // Tier 0 deleted from `Product.calculate_make_cost`. A rate the operator
    // configured is the rate the system must use (Constitution IV).
    const source = wizardSource()
    expect(source).not.toMatch(/assemblyMinutes\s*\/\s*60\s*\)\s*\*\s*10/)
    expect(source).not.toMatch(/const laborCost\b/)
  })

  it('shows no browser-derived total make-cost', () => {
    // Models plus packaging plus labour, with no machine time, waste, yield or
    // overhead, was a second cost implementation on a screen (FR-048).
    const source = wizardSource()
    expect(source).not.toMatch(/const totalCost\b/)
    expect(source).not.toContain('Estimated Total Cost')
    expect(source).toContain('Make-cost is computed after creation')
  })

  it('still totals the model lines, exactly', () => {
    // The inputs stay visible; only the invented total goes.
    const source = wizardSource()
    expect(source).toContain('sumMoney(')
    expect(source).toContain('multiplyMoney(model.total_cost')
  })
})
