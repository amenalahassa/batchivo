// @vitest-environment node
/** Who may write ideas and convert them to products (spec 007, FR-002). */
import { describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ value: undefined as { user: { role: string } | null } | undefined }))
vi.mock('@/contexts/AuthContext', () => ({ useOptionalAuth: () => auth.value }))

import { useIdeaRoles } from './useIdeaRoles'

function useRolesOf(role: string | null) {
  auth.value = { user: role ? { role } : null }
  return useIdeaRoles()
}

describe('useIdeaRoles', () => {
  it('lets owners and admins write and create products', () => {
    expect(useRolesOf('owner')).toEqual({ canWrite: true, canCreateProduct: true })
    expect(useRolesOf('admin')).toEqual({ canWrite: true, canCreateProduct: true })
  })

  it('lets a member write but not create a product', () => {
    expect(useRolesOf('member')).toEqual({ canWrite: true, canCreateProduct: false })
  })

  it('lets a viewer only read', () => {
    expect(useRolesOf('viewer')).toEqual({ canWrite: false, canCreateProduct: false })
  })

  it('gives nothing without a user or an auth provider', () => {
    expect(useRolesOf(null)).toEqual({ canWrite: false, canCreateProduct: false })
    auth.value = undefined
    expect(useIdeaRoles()).toEqual({ canWrite: false, canCreateProduct: false })
  })
})
