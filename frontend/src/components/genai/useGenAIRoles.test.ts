// @vitest-environment node
/** Who may generate and who may change the AI settings (spec 008, Q3). */
import { describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({
  value: undefined as { user: { role: string } | null } | undefined,
}))
vi.mock('@/contexts/AuthContext', () => ({ useOptionalAuth: () => auth.value }))

import { useGenAIRoles } from './useGenAIRoles'

function useRolesOf(role: string | null) {
  auth.value = { user: role ? { role } : null }
  return useGenAIRoles()
}

describe('useGenAIRoles', () => {
  it('lets owners and admins generate and manage settings', () => {
    expect(useRolesOf('owner')).toEqual({ canGenerate: true, canManageSettings: true })
    expect(useRolesOf('admin')).toEqual({ canGenerate: true, canManageSettings: true })
  })

  it('lets a member generate but not manage settings', () => {
    expect(useRolesOf('member')).toEqual({ canGenerate: true, canManageSettings: false })
  })

  it('lets a viewer only look', () => {
    expect(useRolesOf('viewer')).toEqual({ canGenerate: false, canManageSettings: false })
  })

  it('gives nothing without a user', () => {
    expect(useRolesOf(null)).toEqual({ canGenerate: false, canManageSettings: false })
    auth.value = undefined
    expect(useGenAIRoles()).toEqual({ canGenerate: false, canManageSettings: false })
  })
})
