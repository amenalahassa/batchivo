/**
 * What the signed-in operator may do with ideas (spec 007, FR-002).
 *
 * Members and above write ideas and convert to a model; a product needs the
 * same role as creating one on the products screen (admin and above).
 */
import { useOptionalAuth } from '@/contexts/AuthContext'
import { canEditMonetaryPolicy, canEditOperationalFigures } from '@/lib/pricing/permissions'

export function useIdeaRoles() {
  const user = useOptionalAuth()?.user
  return {
    canWrite: canEditOperationalFigures(user),
    canCreateProduct: canEditMonetaryPolicy(user),
  }
}
