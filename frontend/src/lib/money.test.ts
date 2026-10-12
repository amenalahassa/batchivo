/**
 * Money formatting tests.
 *
 * These are the guard on Constitution IV at the last place it can be broken:
 * the moment an exact decimal string is turned into something a person reads.
 * A value too fine for a double is the case that proves it never becomes one.
 */
import { describe, expect, it } from 'vitest'

import { formatMoney, formatShare } from './money'

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
