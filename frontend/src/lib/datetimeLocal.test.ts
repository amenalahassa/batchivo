/**
 * @vitest-environment node
 *
 * Regression (.specify/bugs/complete-run-timezone-500): a datetime-local value
 * round-trips to the same instant whatever the browser's zone.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { fromDateTimeLocalValue, toDateTimeLocalValue } from './datetimeLocal'

const originalTz = process.env.TZ

afterEach(() => {
  process.env.TZ = originalTz
})

describe.each(['America/New_York', 'UTC', 'Asia/Tokyo'])('in %s', (tz) => {
  it('round-trips a start time to the same instant', () => {
    process.env.TZ = tz
    const started = '2026-11-24T15:30:00.000Z'
    const value = toDateTimeLocalValue(new Date(started))
    expect(fromDateTimeLocalValue(value)).toBe(started)
  })
})

describe('toDateTimeLocalValue', () => {
  it('writes local wall-clock time, not UTC', () => {
    process.env.TZ = 'America/New_York'
    // 15:30 UTC is 10:30 in New York (EST, UTC-5)
    expect(toDateTimeLocalValue(new Date('2026-11-24T15:30:00Z'))).toBe('2026-11-24T10:30')
  })
})
