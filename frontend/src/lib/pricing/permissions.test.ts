/**
 * @vitest-environment node
 *
 * No DOM here, so no jsdom. Building one costs more than this file's tests
 * take to run, and a budget spent before a test starts is what made the suite
 * depend on how loaded the machine was (task T174, Constitution II).
 */
/**
 * The two permission tiers, and the read that is never restricted.
 *
 * FR-007a (monetary policy: admin or owner), FR-007b (operational figures:
 * member too), FR-007c (costs visible to everyone).
 */

import { describe, expect, it } from 'vitest'

import {
  canEditMonetaryPolicy,
  canEditOperationalFigures,
  canViewCosts,
} from './permissions'

import type { TenantRole } from '@/lib/auth'

function user(role: TenantRole | null | undefined) {
  return { role }
}

describe('canEditMonetaryPolicy (FR-007a)', () => {
  it.each<TenantRole>(['owner', 'admin'])('allows %s', (role) => {
    expect(canEditMonetaryPolicy(user(role))).toBe(true)
  })

  it.each<TenantRole>(['member', 'viewer'])('refuses %s', (role) => {
    expect(canEditMonetaryPolicy(user(role))).toBe(false)
  })

  it('refuses a member, who may edit measurements but not money', () => {
    // The distinction FR-007a/FR-007b draws: a member records what the printer
    // did; they do not decide what an hour of their time costs.
    expect(canEditOperationalFigures(user('member'))).toBe(true)
    expect(canEditMonetaryPolicy(user('member'))).toBe(false)
  })
})

describe('canEditOperationalFigures (FR-007b)', () => {
  it.each<TenantRole>(['owner', 'admin', 'member'])('allows %s', (role) => {
    expect(canEditOperationalFigures(user(role))).toBe(true)
  })

  it('refuses a viewer', () => {
    expect(canEditOperationalFigures(user('viewer'))).toBe(false)
  })
})

describe('canViewCosts (FR-007c)', () => {
  it.each<TenantRole>(['owner', 'admin', 'member', 'viewer'])('allows %s', (role) => {
    expect(canViewCosts(user(role))).toBe(true)
  })

  it('allows a user whose role is unknown', () => {
    // Visibility is never restricted by role, so an absent role must not
    // blank a cost screen -- only its controls.
    expect(canViewCosts(user(null))).toBe(true)
    expect(canViewCosts(undefined)).toBe(true)
  })
})

describe('an unknown role', () => {
  it('may edit nothing', () => {
    // An older token, or a user outside any tenant. Offering a control the API
    // will refuse costs the operator their typing; withholding it costs a
    // reload.
    for (const absent of [null, undefined]) {
      expect(canEditMonetaryPolicy(user(absent))).toBe(false)
      expect(canEditOperationalFigures(user(absent))).toBe(false)
    }
    expect(canEditMonetaryPolicy(null)).toBe(false)
    expect(canEditOperationalFigures(undefined)).toBe(false)
  })
})
