// @vitest-environment node
/** Display helpers of the Preflight screens (spec 009). */
import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { blockText, isPlaceholder, isValidClearance, preflightErrorText, valueText } from './preflightText'

describe('blockText', () => {
  it('writes nested mappings and lists as YAML blocks', () => {
    expect(blockText({ loads: [{ value: 5, unit: 'kg' }], env: { outdoor: false } })).toBe(
      'loads:\n  - value: 5\n    unit: kg\nenv:\n  outdoor: false\n'
    )
  })

  it('quotes what YAML would read differently', () => {
    const text = blockText({ a: '[À PRÉCISER]', b: 'yes', c: '0.15', d: 'a: b', e: 'plain text' })
    expect(text).toContain('a: "[À PRÉCISER]"')
    expect(text).toContain('b: "yes"')
    expect(text).toContain('c: "0.15"')
    expect(text).toContain('d: "a: b"')
    expect(text).toContain('e: plain text')
  })

  it('keeps empty collections and nulls', () => {
    expect(blockText({ images: [], dims: {}, cycles: null })).toBe('images: []\ndims: {}\ncycles: null\n')
  })
})

describe('isValidClearance', () => {
  it.each(['0', '0.1', '0.15', '0.150', '1.999', '2', '2.000'])('accepts %s', (v) => {
    expect(isValidClearance(v)).toBe(true)
  })
  it.each(['', '-0.1', '2.001', '0.1234', '3', 'abc', '.5', '0,15'])('refuses %s', (v) => {
    expect(isValidClearance(v)).toBe(false)
  })
})

describe('values', () => {
  it('recognises the placeholder', () => {
    expect(isPlaceholder('[À PRÉCISER]')).toBe(true)
    expect(isPlaceholder(null)).toBe(true)
    expect(isPlaceholder('crochet')).toBe(false)
  })

  it('reads booleans and empties', () => {
    expect(valueText(true)).toBe('yes')
    expect(valueText(undefined)).toBe('—')
    expect(valueText(80)).toBe('80')
  })
})

function refused(status: number, detail: unknown): AxiosError {
  const headers = new AxiosHeaders()
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', { headers }, null, {
    status,
    statusText: '',
    headers,
    config: { headers },
    data: { detail },
  })
}

describe('preflightErrorText', () => {
  it('says where a validation failure is', () => {
    const error = refused(422, [
      { loc: ['body', 'intent_yaml', 'loads', 0, 'duration'], msg: 'must be one of cyclic' },
      { loc: ['body', 'value_mm'], msg: 'too small' },
    ])
    expect(preflightErrorText(error)).toBe(
      'intent_yaml.loads[0].duration: must be one of cyclic; value_mm: too small'
    )
  })

  it('falls back to the plain refusal', () => {
    expect(preflightErrorText(refused(409, 'Already started'))).toBe('Already started')
    expect(preflightErrorText(new Error('offline'))).toBe('offline')
  })
})
