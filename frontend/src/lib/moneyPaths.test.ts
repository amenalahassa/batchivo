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

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

function sourceOf(...parts: string[]): string {
  return readFileSync(join(SRC, ...parts), 'utf8')
}

/** Every surface Phase 14 moved onto the decimal helpers. */
const MONEY_SURFACES: Array<[label: string, path: string[]]> = [
  ['the spool card', ['components', 'inventory', 'SpoolCard.tsx']],
  ['the spool dialog', ['components', 'inventory', 'ViewSpoolDialog.tsx']],
  ['the add-spool dialog', ['components', 'inventory', 'AddSpoolDialog.tsx']],
  ['the model list', ['components', 'models', 'ModelList.tsx']],
  ['the BOM editor', ['components', 'models', 'BOMEditor.tsx']],
  ['the channel list', ['components', 'sales-channels', 'SalesChannelList.tsx']],
  ['the channel detail', ['components', 'sales-channels', 'SalesChannelDetail.tsx']],
  ['the run wizard', ['components', 'production-runs', 'CreateRunWizard.tsx']],
  ['the price finder', ['components', 'pricing', 'PriceFinderDialog.tsx']],
  // T201/T202 moved the last three. The order pages read five figures that
  // crossed the wire as JSON numbers until the schemas were retyped, and the
  // designer list sent a `Numeric(10,2)` membership cost back through
  // `parseFloat`.
  ['the order list', ['components', 'orders', 'OrderList.tsx']],
  ['the order detail', ['components', 'orders', 'OrderDetail.tsx']],
  ['the order create form', ['components', 'orders', 'OrderCreateForm.tsx']],
  ['the designer list', ['components', 'designers', 'DesignerList.tsx']],
]

/** The money field names these surfaces are checked against. */
const MONEY_FIELDS = [
  'purchase_price',
  'monthly_cost',
  'total_cost',
  'cost_per_gram',
  'currentPrice',
  // T201/T202.
  'membership_cost',
  'unit_price',
  'total_price',
  'shipping_cost',
  'subtotal',
]

describe('no money figure is put through a double', () => {
  it.each(MONEY_SURFACES)('%s calls no parseFloat on a money field', (_label, path) => {
    const source = sourceOf(...path)
    // Weights, quantities and percentages are not money and may be numbers.
    // These are the fields the engine prices from.
    for (const field of MONEY_FIELDS) {
      expect(source).not.toMatch(new RegExp(`parseFloat\\(\\s*[\\w.]*${field}`))
      expect(source).not.toMatch(new RegExp(`Number\\.parseFloat\\(\\s*[\\w.]*${field}`))
    }
  })

  it.each(MONEY_SURFACES)('%s calls no toFixed on a money field', (_label, path) => {
    const source = sourceOf(...path)
    // No bare `total`: `totalCurrent`, `totalActual` and `total_weight_grams`
    // are grams, so the word says nothing about whether a figure is money.
    for (const field of [...MONEY_FIELDS, 'estCost']) {
      expect(source).not.toMatch(new RegExp(`${field}[\\w.]*\\.toFixed\\(`))
    }
  })
})

describe('every amount is labelled in the tenant currency', () => {
  it.each(MONEY_SURFACES)('%s hardcodes no currency symbol beside a figure', (_label, path) => {
    const source = sourceOf(...path)
    // A `£` in a field *label* is a prompt about what to type, not a figure
    // the system reported, so only interpolations are checked here.
    expect(source).not.toMatch(/£\$\{/)
    expect(source).not.toMatch(/£\{/)
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
