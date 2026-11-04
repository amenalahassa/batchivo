/**
 * Packaging Page (spec 006)
 *
 * Boxes, mailers, void fill and wrap, apart from the other consumables.
 */

import { AppLayout } from '@/components/layout/AppLayout'
import { PackagingList } from '@/components/packaging/PackagingList'

export function Packaging() {
  return (
    <AppLayout>
      <PackagingList />
    </AppLayout>
  )
}
