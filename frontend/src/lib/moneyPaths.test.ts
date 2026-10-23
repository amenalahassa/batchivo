/**
 * @vitest-environment node
 *
 * No DOM here, so no jsdom. Building one costs more than this file's tests
 * take to run, and a budget spent before a test starts is what made the suite
 * depend on how loaded the machine was (task T174, Constitution II).
 */
/**
 * Money reaches the screen as the decimal string the API sent (Phase 14).
 *
 * Source-level assertions, for the reason `ModelDetail.test.tsx` gives: the
 * defects here are *constructs*, not rendered strings. `parseFloat(a) * b`
 * and an exact decimal multiplication print the same number for almost every
 * input, so a snapshot cannot tell them apart — and the one input where they
 * differ is the one nobody tried.
 *
 * Two of these shipped as real faults rather than as drift. `purchase_price`
 * became a decimal string on the wire when its schema became a `Decimal`
 * (T152), and four screens kept calling `.toFixed(2)` on it, which throws at
 * render (T158). The run wizard priced filament with a hardcoded `0.02` per
 * gram when a spool carried no price — a figure no operator configured, which
 * Constitution IV rules out (T163).
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

function sourceOf(...parts: string[]): string {
  return readFileSync(join(SRC, ...parts), 'utf8')
}

// ============================================
// The population, derived rather than listed (T211)
// ============================================
//
// This file used to parametrise over thirteen named components, while
// thirty-eight render money and the screens that *send* money were not
// counted at all -- which is where T209 and T210 both lived. Each round added
// the screens it had just fixed to the list, which fixed those screens and
// left the guard as narrow as before. The backend sweep was derived in T206;
// this is the same change on this side: every component, API module and type
// module is walked, the money-name rule is applied to every identifier, and
// what is excused is named by *field*, with the reason, rather than by file.

function walk(dir: string): string[] {
  const found: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      found.push(...walk(path))
    } else if (/\.tsx?$/.test(entry) && !/\.(test|stories)\.tsx?$/.test(entry)) {
      found.push(path)
    }
  }
  return found
}

const label = (path: string) => relative(SRC, path).split(sep).join('/')

/** Every component, and every module that declares what crosses the wire. */
const SURFACES = [
  ...walk(join(SRC, 'components')),
  ...walk(join(SRC, 'lib', 'api')),
  ...walk(join(SRC, 'types')),
].sort()

/** The modules whose declarations are the wire format. */
const DECLARATIONS = SURFACES.filter(
  (path) => label(path).startsWith('lib/api/') || label(path).startsWith('types/'),
)

/**
 * Name fragments that mean "this is an amount of money" -- the backend's
 * `MONEY_NAME_PARTS` in `test_no_float_in_money_paths.py`, so the two sides of
 * the wire apply one rule. Deliberately without `rate` and a bare `total`:
 * `success_rate` and `total_weight_grams` are not money.
 */
const MONEY_NAME_PARTS = [
  'cost',
  'price',
  'fee',
  'amount',
  'revenue',
  'profit',
  'margin',
  'charge',
  'tax',
  'reserve',
  'subtotal',
  'discount',
  'refund',
  'markup',
  'surcharge',
  'postage',
  'value',
]

/**
 * A last word that makes a money-sounding name something else.
 *
 * `margin_pct` and `expected_discount_pct` are percentages, `waste_cost_grams`
 * a weight, `price_id` and `fee_rule` references, `margin_basis` a choice of
 * formula. The *last* word carries the unit, which is why `cost_per_gram`
 * stays money.
 */
const NOT_MONEY_SUFFIXES = new Set([
  'pct',
  'percent',
  'percentage',
  'ratio',
  'grams',
  'count',
  'days',
  'hours',
  'minutes',
  'id',
  'ids',
  'rule',
  'rules',
  'type',
  'mode',
  'basis',
  'source',
  'label',
  'key',
  'name',
  'status',
  'provenance',
  'origin',
  'at',
  'date',
  'currency',
  'code',
])

/**
 * Names the rule calls money that are not, each with why.
 *
 * `OrderCounts.refunded` is a count of orders too, but `refunded` is not a
 * money part (`refund` is, and the rule does not stem), so it needs no entry.
 */
const NOT_MONEY_BY_NAME: Record<string, string> = {
  models_with_actual_cost: 'a count of models carrying an actual cost, not an amount',
  value: "the DOM's input value and every setter's generic argument",
}

function words(name: string): string[] {
  return name
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .split('_')
    .filter(Boolean)
}

function hasMoneyPart(name: string): boolean {
  return words(name).some((part) => MONEY_NAME_PARTS.includes(part.replace(/s$/, '')))
}

function namesMoney(name: string): boolean {
  if (name in NOT_MONEY_BY_NAME) return false
  const parts = words(name)
  if (parts.length === 0 || NOT_MONEY_SUFFIXES.has(parts[parts.length - 1])) return false
  return hasMoneyPart(name)
}

/** Source lines with comments blanked, so prose about a defect is not the defect. */
function code(path: string): string[] {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '))
    .split('\n')
    .map((line) => line.replace(/(^|[^:'"`])\/\/.*$/, '$1'))
}

/** The identifier an expression ends on: `formData.purchase_price` gives `purchase_price`. */
function lastName(expression: string): string {
  return expression.match(/([A-Za-z_$][\w$]*)[\])?!]*$/)?.[1] ?? ''
}

const READ = /\b(?:Number\.)?parseFloat\(\s*([\w$.?!\]]+)(?![\w$.?!\]]*\s*\()|\bNumber\(\s*([\w$.?!\]]+)(?![\w$.?!\]]*\s*\()/g
const ROUND = /([\w$.?!\]]+)\)?\.toFixed\(/g
const WRITE_BY_KEY = /['"]([\w$]+)['"]\s*,[^\n]*?(?:parseFloat\(|\bNumber\(|valueAsNumber)/g
const WRITE_BY_PROPERTY = /\b([\w$]+)\s*:\s*(?:Number\.)?(?:parseFloat|Number)\(/g

/** Every place a money-named value is put through a double. */
function doublesOnMoney(path: string): string[] {
  const found: string[] = []
  code(path).forEach((line, index) => {
    const at = `${label(path)}:${index + 1}`
    // Reading: `parseFloat(x.price)`, `Number(x.cost)`. A call such as
    // `Number(form.getValues('quantity'))` ends in `(`, so is not a field.
    for (const m of line.matchAll(READ)) {
      const name = lastName(m[1] ?? m[2])
      if (namesMoney(name)) found.push(`${at} reads ${name} as a double`)
    }
    // Rounding: `x.price.toFixed(2)`, which throws on the string the API sends.
    for (const m of line.matchAll(ROUND)) {
      const name = lastName(m[1])
      if (namesMoney(name)) found.push(`${at} calls toFixed on ${name}`)
    }
    // Writing: a setter or `register` naming a money field and handing it a
    // double -- T209 and T210 were `set('purchase_price', parseFloat(...))`.
    for (const m of line.matchAll(WRITE_BY_KEY)) {
      if (namesMoney(m[1])) found.push(`${at} writes ${m[1]} as a double`)
    }
    for (const m of line.matchAll(WRITE_BY_PROPERTY)) {
      if (namesMoney(m[1])) found.push(`${at} writes ${m[1]} as a double`)
    }
  })
  return found
}

/** Every money-named field a type or API module declares as `number`. */
function moneyDeclaredNumber(path: string): string[] {
  const found: string[] = []
  code(path).forEach((line, index) => {
    const m = line.match(/^\s*([\w$]+)\??\s*:\s*number\b/)
    if (m && namesMoney(m[1])) found.push(`${label(path)}:${index + 1} declares ${m[1]}: number`)
  })
  return found
}

describe('the population is derived, and is the whole app', () => {
  it('walks every component and wire module, not a hand-picked few', () => {
    expect(SURFACES.length).toBeGreaterThan(150)
    expect(DECLARATIONS.length).toBeGreaterThan(25)
  })

  it.each([
    // The thirteen this file used to name, and the screens T209/T210 found.
    'components/inventory/SpoolCard.tsx',
    'components/inventory/ViewSpoolDialog.tsx',
    'components/inventory/AddSpoolDialog.tsx',
    'components/inventory/EditSpoolDialog.tsx',
    'components/inventory/AddConsumableDialog.tsx',
    'components/inventory/EditConsumableDialog.tsx',
    'components/models/ModelList.tsx',
    'components/models/BOMEditor.tsx',
    'components/sales-channels/SalesChannelList.tsx',
    'components/sales-channels/SalesChannelDetail.tsx',
    'components/production-runs/CreateRunWizard.tsx',
    'components/pricing/PriceFinderDialog.tsx',
    'components/orders/OrderList.tsx',
    'components/orders/OrderDetail.tsx',
    'components/orders/OrderCreateForm.tsx',
    'components/designers/DesignerList.tsx',
    'lib/api/orders.ts',
    'types/spool.ts',
    'types/consumable.ts',
  ])('includes %s', (path) => {
    expect(SURFACES.map(label)).toContain(path)
  })
})

describe('the money-name rule says what it means', () => {
  it.each([
    'purchase_price',
    'current_cost_per_unit',
    'cost_per_gram',
    'membership_cost',
    'stock_value',
    'shipping_cost',
    'subtotal',
    'costPerSpool',
    'estCost',
    'total_price',
  ])('%s is money', (name) => {
    expect(namesMoney(name)).toBe(true)
  })

  it.each([
    'margin_pct',
    'expected_discount_pct',
    'total_weight_grams',
    'price_id',
    'fee_rule',
    'margin_basis',
    'cost_source',
    'refunded',
    'value',
    'models_with_actual_cost',
    'quantity',
  ])('%s is not', (name) => {
    expect(namesMoney(name)).toBe(false)
  })

  it.each(Object.keys(NOT_MONEY_BY_NAME))(
    'the exception %s is one the rule would otherwise flag',
    (name) => {
      // An exception the rule no longer needs excuses nothing and hides the
      // next field that happens to share its name.
      expect(hasMoneyPart(name)).toBe(true)
    },
  )

  it('catches the shapes T209, T210 and the onboarding price shipped as', () => {
    // The sweep is shown to find what it exists to find, not merely to find
    // nothing.
    const shipped = [
      `handleInputChange('purchase_price', e.target.value ? parseFloat(e.target.value) : undefined)`,
      `handleInputChange('current_cost_per_unit', e.target.value ? parseFloat(e.target.value) : null)`,
      `{...register('product_price', { valueAsNumber: true })}`,
    ]
    for (const line of shipped) {
      const keys = [...line.matchAll(WRITE_BY_KEY)].map((m) => m[1])
      expect(keys.some(namesMoney)).toBe(true)
    }
    expect([...'parseFloat(spool.purchase_price)'.matchAll(READ)].map((m) => lastName(m[1]))).toEqual([
      'purchase_price',
    ])
    expect([...'Number(form.getValues(x))'.matchAll(READ)]).toEqual([])
  })
})

describe('no money figure is put through a double', () => {
  it('no component, API or type module reads, rounds or writes money as a number', () => {
    expect(SURFACES.flatMap(doublesOnMoney)).toEqual([])
  })

  it('no API or type module declares a money field as number', () => {
    expect(DECLARATIONS.flatMap(moneyDeclaredNumber)).toEqual([])
  })
})

describe('every amount is labelled in the tenant currency', () => {
  it('no surface hardcodes a currency symbol beside a figure', () => {
    // A `£` in a field *label* is a prompt about what to type, not a figure
    // the system reported, so only interpolations are checked here.
    const findings = SURFACES.flatMap((path) =>
      code(path).flatMap((line, index) =>
        /£\$\{|£\{/.test(line) ? [`${label(path)}:${index + 1}`] : [],
      ),
    )
    expect(findings).toEqual([])
  })
})

describe('the run wizard prices no filament the operator did not configure', () => {
  const source = sourceOf('components', 'production-runs', 'CreateRunWizard.tsx')

  it('has no hardcoded per-gram fallback', () => {
    // `: 0.02 // Default fallback` costed every spool with no recorded price
    // at a figure nobody chose, and did it silently.
    expect(source).not.toMatch(/:\s*0\.02\b/)
  })

  it('derives its estimate with the decimal helpers', () => {
    expect(source).toContain('multiplyMoney(mat.cost_per_gram')
    expect(source).toContain('sumMoney(')
  })
})

describe('no second material-cost implementation lives in the API layer', () => {
  it('has no browser-side estimated material cost helper', () => {
    // `calculateEstimatedMaterialCost` summed `weight * cost_per_gram` as
    // doubles and had no reader. Constitution III says remove a parallel
    // implementation rather than keep it in step.
    const source = sourceOf('lib', 'api', 'production-runs.ts')
    expect(source).not.toContain('calculateEstimatedMaterialCost')
  })
})

describe('the order money is typed as it crosses the wire (T201)', () => {
  const source = sourceOf('lib', 'api', 'orders.ts')

  it('serves the five order figures as Money strings, not numbers', () => {
    // These were the last money fields on this API crossing the wire as JSON
    // numbers. They were pinned by name in the backend float ban's
    // `ROUTE_LAYER_LEGACY_FLOAT_FIELDS` rather than fixed, because correcting
    // them changes the wire format these screens read; T201 did both halves
    // and removed the hold.
    //
    // `total` is deliberately absent from the loop: `OrderListResponse.total`
    // and `OrderCounts.total` are *counts*, and a bare `total` cannot be told
    // from money by its name alone -- the same reason the backend's
    // `MONEY_NAME` omits the word. It is checked on `Order` itself below.
    for (const field of ['unit_price', 'total_price', 'shipping_cost', 'subtotal']) {
      expect(source).not.toMatch(new RegExp(`\\n\\s*${field}:\\s*number\\b`))
      expect(source).toMatch(new RegExp(`\\n\\s*${field}:\\s*Money\\b`))
    }
  })

  it('serves the order total as a Money string', () => {
    const order = source.slice(
      source.indexOf('export interface Order {'),
      source.indexOf('export interface OrderListResponse'),
    )
    expect(order).toMatch(/\n\s*total:\s*Money\b/)
    expect(order).not.toMatch(/\n\s*total:\s*number\b/)
  })
})

describe('the designer membership cost is typed as it crosses the wire (T202)', () => {
  it('is a Money string on every designer request and response', () => {
    const source = sourceOf('lib', 'api', 'designers.ts')
    expect(source).not.toMatch(/membership_cost\??:\s*number/)
    expect(source).toMatch(/membership_cost\??:\s*Money/)
  })
})

describe('the spool price is typed as it crosses the wire', () => {
  it('is a Money string, not a number', () => {
    // The column is `Numeric` and the schema is a `Decimal`, which this app
    // serialises as a JSON string — asserted on the backend in
    // `test_printer_cost_policy.py`. A `number` here is a lie the compiler
    // believes, and `.toFixed` on it throws at render.
    const source = sourceOf('types', 'spool.ts')
    expect(source).not.toMatch(/purchase_price\?:\s*number/)
    expect(source).toMatch(/purchase_price\?:\s*Money/)
  })
})
