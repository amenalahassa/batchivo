/**
 * Money formatting tests.
 *
 * These are the guard on Constitution IV at the last place it can be broken:
 * the moment an exact decimal string is turned into something a person reads.
 * A value too fine for a double is the case that proves it never becomes one.
 */
import { describe, expect, it } from 'vitest'

import { formatMoney, formatShare, formatPercent, symbolForCurrency } from './money'

describe('formatMoney', () => {
  it('keeps the cents a decimal string carries', () => {
    expect(formatMoney('20.30')).toBe('$20.30')
  })

  it('pads a single decimal place rather than dropping it', () => {
    expect(formatMoney('20.3')).toBe('$20.30')
  })

  it('pads a whole number', () => {
    expect(formatMoney('20')).toBe('$20.00')
  })

  it('rounds a long tail at the cent, by string surgery not by float', () => {
    // 0.023986666... is a real per-gram cost; it must not become 0.024 or 0.
    expect(formatMoney('0.023986666')).toBe('$0.02')
    expect(formatMoney('0.025')).toBe('$0.03')
  })

  it('carries a rounding bump into the whole part', () => {
    expect(formatMoney('19.999')).toBe('$20.00')
  })

  it('keeps a negative sign', () => {
    expect(formatMoney('-1.50')).toBe('-$1.50')
  })

  it('renders a missing amount as a dash, never as zero', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney('')).toBe('—')
  })

  it('does not lose precision a float would', () => {
    // 1e-16 survives only because the value never becomes a double.
    expect(formatMoney('0.0000000000000001')).toBe('$0.00')
  })
})

describe('formatShare', () => {
  it('renders a fraction as a whole percentage', () => {
    expect(formatShare('0.9200')).toBe('92%')
    expect(formatShare('1')).toBe('100%')
    expect(formatShare('0')).toBe('0%')
  })

  it('renders a missing share as a dash', () => {
    expect(formatShare(null)).toBe('—')
  })
})

describe('formatPercent', () => {
  it('rounds four decimals to one place, as a screen shows it', () => {
    // The acceptance case: the engine reports 35.2693 and the screen says 35.3%.
    expect(formatPercent('35.2693')).toBe('35.3%')
  })

  it('rounds up at the midpoint', () => {
    expect(formatPercent('35.2500')).toBe('35.3%')
  })

  it('rounds down below the midpoint', () => {
    expect(formatPercent('35.2499')).toBe('35.2%')
  })

  it('carries into the whole number when the fraction rounds over', () => {
    expect(formatPercent('35.9999')).toBe('36.0%')
  })

  it('pads a short fraction rather than truncating the place', () => {
    expect(formatPercent('35.2')).toBe('35.2%')
    expect(formatPercent('35')).toBe('35.0%')
  })

  it('keeps a negative margin negative', () => {
    expect(formatPercent('-12.4500')).toBe('-12.5%')
  })

  it('honours a requested number of places', () => {
    expect(formatPercent('6.5000', { places: 2 })).toBe('6.50%')
    expect(formatPercent('19.5000', { places: 0 })).toBe('20%')
  })

  it('reports a null percentage as undefined, never as zero', () => {
    // The net-revenue basis with fees consuming the whole amount has no
    // percentage. A zero there would read as break-even.
    expect(formatPercent(null)).toBe('undefined')
    expect(formatPercent(undefined)).toBe('undefined')
    expect(formatPercent('')).toBe('undefined')
  })

  it('takes a caller-supplied word for the undefined case', () => {
    expect(formatPercent(null, { undefinedLabel: 'Undefined' })).toBe('Undefined')
  })

  it('never parses the value into a float on the rounding path', () => {
    // A value with more precision than a double carries exactly. Going
    // through Number() would be lossy here, which is the defect this whole
    // module exists to avoid (Constitution IV).
    expect(formatPercent('35.26934999999999999999')).toBe('35.3%')
  })
})

describe('symbolForCurrency', () => {
  it('gives the glyph for a currency it knows', () => {
    expect(symbolForCurrency('GBP')).toBe('£')
    expect(symbolForCurrency('CAD')).toBe('CA$')
  })

  it('accepts a lowercase or padded code', () => {
    expect(symbolForCurrency(' cad ')).toBe('CA$')
  })

  it('falls back to the code itself rather than guessing a glyph', () => {
    // "CHF 20.30" is plain and cannot be wrong; a guessed symbol could state
    // the amount in the wrong currency.
    expect(symbolForCurrency('CHF')).toBe('CHF ')
  })

  it('uses the caller fallback when no code is known at all', () => {
    expect(symbolForCurrency(null, '£')).toBe('£')
    expect(symbolForCurrency(undefined, '£')).toBe('£')
    expect(symbolForCurrency('', '£')).toBe('£')
  })
})
