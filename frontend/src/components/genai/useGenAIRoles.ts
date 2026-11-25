/**
 * What the signed-in operator may do with generative AI (spec 008, clarification Q3).
 *
 * Owners, admins and members generate, cancel and adopt; viewers only look.
 * The Replicate settings (token, budget, models) are for admins and owners.
 */
import { useOptionalAuth } from '@/contexts/AuthContext'
import { canEditMonetaryPolicy, canEditOperationalFigures } from '@/lib/pricing/permissions'

export function useGenAIRoles() {
  const user = useOptionalAuth()?.user
  return {
    canGenerate: canEditOperationalFigures(user),
    canManageSettings: canEditMonetaryPolicy(user),
  }
}
