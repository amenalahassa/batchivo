// @vitest-environment node
/** Which Settings tab `?tab=` opens (spec 008, US1 AS5, T060). */
import { describe, expect, it } from 'vitest'

import { initialSettingsTab } from './settingsTab'

describe('initialSettingsTab', () => {
  it('opens a known tab', () => {
    expect(initialSettingsTab('?tab=ai', true)).toBe('ai')
    expect(initialSettingsTab('?tab=pricing', false)).toBe('pricing')
    expect(initialSettingsTab('?other=1&tab=team', false)).toBe('team')
  })

  it('opens the AI tab only for someone who can see it', () => {
    expect(initialSettingsTab('?tab=ai', false)).toBe('general')
  })

  it('ignores unknown or missing values', () => {
    expect(initialSettingsTab('?tab=__proto__', true)).toBe('general')
    expect(initialSettingsTab('?tab=AI', true)).toBe('general')
    expect(initialSettingsTab('', true)).toBe('general')
  })
})
