// @vitest-environment node
import { describe, expect, it } from 'vitest'

import { CAPABILITY_LABELS, failureMessage, priceText, refusalMessage, usd } from './genaiText'

describe('genaiText', () => {
  it('labels every capability', () => {
    expect(Object.keys(CAPABILITY_LABELS)).toHaveLength(7)
  })

  it('keeps money as the server sent it', () => {
    expect(usd('0.0030')).toBe('$0.0030 USD')
    expect(usd(null)).toBe('—')
  })

  it('shows the budget refusal as the server worded it', () => {
    const message = 'This generation (about $0.0030) would go over the monthly budget of $1.00.'
    expect(refusalMessage({ code: 'budget_exceeded', message })).toBe(message)
  })

  it('falls back to a readable refusal', () => {
    expect(refusalMessage({ code: 'not_connected', message: '' })).toMatch(/Settings → AI/)
    expect(refusalMessage(null)).toBeNull()
  })

  it('explains failures', () => {
    expect(failureMessage('timeout', null)).toMatch(/too long/)
    expect(failureMessage(null, 'NSFW content')).toBe('NSFW content')
  })

  it('prices with unit and approximation', () => {
    expect(
      priceText({ unit: 'per_output', amount_usd: '0.003', source: 'catalog', assumed: false })
    ).toBe('$0.003 per image')
    expect(
      priceText({ unit: 'per_run', amount_usd: '0.04', source: 'catalog', assumed: true })
    ).toBe('$0.04 per run (approximate)')
  })
})
