/**
 * @vitest-environment node
 *
 * No DOM here, so no jsdom. Building one costs more than this file's tests
 * take to run, and a budget spent before a test starts is what made the suite
 * depend on how loaded the machine was (task T174, Constitution II).
 */
/**
 * Money formatting tests.
 *
 * These are the guard on Constitution IV at the last place it can be broken:
 * the moment an exact decimal string is turned into something a person reads.
 * A value too fine for a double is the case that proves it never becomes one.
 */
import { describe, expect, it } from 'vitest'

import {
  addMoney,
  averageMoney,
  divideMoney,
  formatMoney,
  formatPercent,
  formatShare,
  multiplyMoney,
  subtractMoney,
  sumMoney,
  symbolForCurrency,
} from './money'

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

  // A single printed item's cost is often fractions of a unit, so the model
  // screen reads it to three places. The places are an argument rather than a
  // second formatter, so there is still one place money is rendered (task
  // T151).
  describe('at a places other than two', () => {
    it('keeps three decimals where the caller asks for them', () => {
      expect(formatMoney('0.023986666', '$', { places: 3 })).toBe('$0.024')
      expect(formatMoney('1.5', '£', { places: 3 })).toBe('£1.500')
    })

    it('rounds at the place asked for, half-up, in string space', () => {
      expect(formatMoney('0.0235', '$', { places: 3 })).toBe('$0.024')
      expect(formatMoney('0.0234', '$', { places: 3 })).toBe('$0.023')
    })

    it('carries a bump into the whole part at any places', () => {
      expect(formatMoney('19.9995', '$', { places: 3 })).toBe('$20.000')
      expect(formatMoney('19.6', '$', { places: 0 })).toBe('$20')
    })

    it('drops the point entirely at zero places', () => {
      expect(formatMoney('20.30', '$', { places: 0 })).toBe('$20')
    })

    it('still shows a missing amount as a dash', () => {
      expect(formatMoney(null, '$', { places: 3 })).toBe('—')
    })
  })
})

describe('subtractMoney', () => {
  it('takes the difference exactly, at the wider scale', () => {
    expect(subtractMoney('20.30', '18.05')).toBe('2.25')
    expect(subtractMoney('20.3', '18.005')).toBe('2.295')
  })

  it('returns a signed difference when the second is larger', () => {
    expect(subtractMoney('18.00', '20.30')).toBe('-2.30')
  })

  it('reports an exact match as zero, which a float does not', () => {
    // 0.3 - 0.1 - 0.2 is -2.7755575615628914e-17 as doubles, which renders as
    // an overrun on a run that matched plan.
    expect(subtractMoney(subtractMoney('0.3', '0.1'), '0.2')).toBe('0.0')
    expect(Number(subtractMoney(subtractMoney('0.3', '0.1'), '0.2'))).toBe(0)
  })

  it('negates the second side when the first is missing', () => {
    expect(subtractMoney(null, '2.50')).toBe('-2.50')
  })

  it('returns the first side when the second is missing', () => {
    expect(subtractMoney('2.50', null)).toBe('2.50')
  })

  it('is zero when neither side is a figure', () => {
    expect(subtractMoney(null, undefined)).toBe('0')
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

/**
 * The arithmetic the product screens do on top of the engine's figures.
 *
 * Each case below is one a `parseFloat` implementation gets wrong, which is
 * the point: these are not tests that addition works, they are the guard that
 * a line total and the column it sits in cannot disagree by a cent.
 */
describe('addMoney', () => {
  it('adds two amounts float addition gets wrong', () => {
    // 0.1 + 0.2 === 0.30000000000000004 as doubles.
    expect(addMoney('0.10', '0.20')).toBe('0.30')
  })

  it('keeps the wider of the two scales', () => {
    expect(addMoney('1.5', '2.25')).toBe('3.75')
    expect(addMoney('0.001', '0.002')).toBe('0.003')
  })

  it('carries across the decimal point', () => {
    expect(addMoney('0.99', '0.01')).toBe('1.00')
  })

  it('subtracts when an amount is negative', () => {
    expect(addMoney('5.00', '-7.50')).toBe('-2.50')
    expect(addMoney('-0.10', '0.10')).toBe('0.00')
  })

  it('treats a missing or malformed amount as contributing nothing', () => {
    // A single bad figure must not turn a whole column into NaN.
    expect(addMoney('1.00', null)).toBe('1.00')
    expect(addMoney(undefined, '2.00')).toBe('2.00')
    expect(addMoney('1.00', 'not money')).toBe('1.00')
    expect(addMoney(null, null)).toBe('0')
  })
})

describe('sumMoney', () => {
  it('sums a column exactly where repeated float addition drifts', () => {
    // Ten additions of 0.1 as doubles reach 0.9999999999999999.
    expect(sumMoney(Array.from({ length: 10 }, () => '0.1'))).toBe('1.0')
  })

  it('sums an empty column to zero rather than to a dash', () => {
    expect(sumMoney([])).toBe('0')
  })

  it('skips the holes in a column', () => {
    expect(sumMoney(['1.25', null, '2.75', undefined])).toBe('4.00')
  })
})

describe('multiplyMoney', () => {
  it('multiplies a unit cost by a count exactly', () => {
    // 0.07 * 3 === 0.21000000000000002 as doubles.
    expect(multiplyMoney('0.07', 3)).toBe('0.21')
    expect(multiplyMoney('1.10', 3)).toBe('3.30')
  })

  it('keeps every digit the product earns rather than rounding early', () => {
    expect(multiplyMoney('0.005', 3)).toBe('0.015')
  })

  it('accepts the count as a decimal string', () => {
    expect(multiplyMoney('2.00', '2.5')).toBe('5.000')
  })

  it('multiplies by zero to zero, not to a dash', () => {
    expect(multiplyMoney('9.99', 0)).toBe('0.00')
  })

  it('has no product for a missing or malformed amount', () => {
    expect(multiplyMoney(null, 3)).toBe('0')
    expect(multiplyMoney('not money', 3)).toBe('0')
    expect(multiplyMoney('1.00', Number.NaN)).toBe('0')
  })
})

describe('averageMoney', () => {
  it('averages exactly where the float mean lands a cent out', () => {
    expect(averageMoney(['0.10', '0.20', '0.30'])).toBe('0.20')
  })

  it('rounds half up at the requested places, and only there', () => {
    // 1/3 of a penny is not a penny: this is the one rounding allowed here.
    expect(averageMoney(['0.01', '0.00', '0.00'])).toBe('0.00')
    expect(averageMoney(['1.00', '2.00'])).toBe('1.50')
    expect(averageMoney(['0.00', '0.01'])).toBe('0.01')
  })

  it('averages a percentage to the places a screen shows', () => {
    expect(averageMoney(['35.2693', '40.0000'], 1)).toBe('37.6')
  })

  it('averages negatives away from zero on the half', () => {
    expect(averageMoney(['-0.01', '0.00'])).toBe('-0.01')
  })

  it('has no mean for an empty set, so the caller can show a dash', () => {
    // Zero and "no figure at all" are different facts (FR-019).
    expect(averageMoney([])).toBeNull()
    expect(averageMoney([null, undefined, ''])).toBeNull()
  })

  it('averages over the usable figures only', () => {
    expect(averageMoney(['1.00', null, '3.00'])).toBe('2.00')
  })
})

describe('divideMoney', () => {
  it('divides a total into a per-unit cost exactly', () => {
    // A purchase of 7 at £1.05 is 15p each; the float quotient is
    // 0.15000000000000002.
    expect(divideMoney('1.05', 7, 4)).toBe('0.1500')
    expect(divideMoney('10.00', 4)).toBe('2.50')
  })

  it('rounds half up at the requested places, and only once', () => {
    // 10/3 is 3.333...; rounding the quotient twice would land on 3.34.
    expect(divideMoney('10.00', 3, 2)).toBe('3.33')
    expect(divideMoney('10.00', 3, 4)).toBe('3.3333')
    expect(divideMoney('0.05', 2)).toBe('0.03')
  })

  it('divides by a decimal divisor', () => {
    expect(divideMoney('10.00', '2.5')).toBe('4.00')
  })

  it('carries the sign of either side', () => {
    expect(divideMoney('-10.00', 4)).toBe('-2.50')
    expect(divideMoney('10.00', -4)).toBe('-2.50')
  })

  it('has no answer for a division it cannot do', () => {
    // Zero units is not "free each", it is unanswerable (FR-019).
    expect(divideMoney('10.00', 0)).toBeNull()
    expect(divideMoney(null, 4)).toBeNull()
    expect(divideMoney('not money', 4)).toBeNull()
  })
})
