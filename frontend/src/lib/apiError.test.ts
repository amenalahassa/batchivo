/**
 * @vitest-environment node
 *
 * `detailText` reads every shape FastAPI's `detail` takes (bug login-validation-object-object).
 */

import { describe, expect, it } from 'vitest'

import { detailText } from './apiError'

describe('detailText', () => {
  it('returns a plain refusal as is', () => {
    expect(detailText('Invalid credentials')).toBe('Invalid credentials')
  })

  it('joins the messages of a validation error list', () => {
    expect(detailText([{ msg: 'field required' }, { msg: 'too short' }])).toBe(
      'field required; too short',
    )
  })

  it('reads the message of a structured refusal', () => {
    expect(detailText({ message: 'Taken', code: 'slug_taken' })).toBe('Taken')
  })

  it('says nothing for an absent, empty or unreadable detail', () => {
    expect(detailText(undefined)).toBeUndefined()
    expect(detailText('  ')).toBeUndefined()
    expect(detailText([])).toBeUndefined()
    expect(detailText([{ loc: ['body'] }])).toBeUndefined()
  })
})
