/**
 * The one-time notice of what the catalogue seeding added (spec 006, FR-010, FR-022).
 *
 * Shown on the Packaging page (part "packaging") and the shipping profiles
 * panel (part "postage") until the operator dismisses it. The postage notice
 * names the carrier and whether it was chosen from the shop's country or its
 * currency -- or, when nothing could be seeded, says why and points to adding
 * a profile by hand.
 */

import { Info, X } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useAcknowledgeNotice, useCatalogueNotice } from '@/hooks/usePackagingCatalogue'
import type {
  NoticePart,
  PackagingNotice,
  PostageNotice,
} from '@/types/packagingCatalogue'
import type { Carrier } from '@/types/postageCatalogue'

import { CHOICE_REASONS } from './catalogueHelpers'
import { carrierName } from './serviceLabels'

const SKIP_REASONS: Record<string, string> = {
  already_present: 'already on your list',
  name_in_use: 'you already have an item with that name',
  overlaps_existing: 'overlaps one of your own profiles',
}


const CHOSEN_FROM: Record<string, string> = {
  country: 'chosen from your shop’s country',
  currency: 'chosen from your books currency',
  operator: 'chosen by you',
}

function PackagingBody({ notice }: { notice: PackagingNotice }) {
  return (
    <>
      <p>
        {notice.added.length} standard packaging item{notice.added.length === 1 ? '' : 's'} added
        with typical sizes and costs, marked <em>default</em> until you measure or price them.
      </p>
      {notice.skipped.length > 0 && (
        <ul className="mt-1 list-disc pl-5" data-testid="notice-skipped">
          {notice.skipped.map((s) => (
            <li key={s.key}>
              {s.key}: skipped, {SKIP_REASONS[s.reason] ?? s.reason}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function PostageBody({
  notice,
  carriers,
  onAddProfile,
}: {
  notice: PostageNotice
  carriers?: Carrier[]
  onAddProfile?: () => void
}) {
  if (notice.reason) {
    return (
      <>
        <p>No carrier postage was added. {CHOICE_REASONS[notice.reason]}</p>
        <p className="mt-1">
          Enter your own postage instead
          {onAddProfile ? (
            <>
              {' '}
              with{' '}
              <Button variant="link" className="h-auto p-0" onClick={onAddProfile}>
                Add profile
              </Button>
            </>
          ) : null}
          .
        </p>
      </>
    )
  }
  return (
    <>
      <p>
        {notice.added} postage profile{notice.added === 1 ? '' : 's'} added from the{' '}
        <strong>{carrierName(notice.carrier, carriers)}</strong> tariff
        {notice.tariff_version ? ` of ${notice.tariff_version}` : ''},{' '}
        {CHOSEN_FROM[notice.chosen_from ?? ''] ?? 'chosen for you'}.
        {notice.superseded > 0 ? ` ${notice.superseded} older seeded profiles were closed.` : ''}
      </p>
      {notice.skipped.length > 0 && (
        <ul className="mt-1 list-disc pl-5" data-testid="notice-skipped">
          {notice.skipped.map((s) => (
            <li key={`${s.service}-${s.zone}-${s.min_grams}`}>
              {s.service} to {s.zone} from {s.min_grams} g: skipped,{' '}
              {SKIP_REASONS[s.reason] ?? s.reason}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

interface CatalogueNoticeProps {
  part: NoticePart
  carriers?: Carrier[]
  /** Postage only: opens the panel's own "Add profile" form. */
  onAddProfile?: () => void
}

export function CatalogueNotice({ part, carriers, onAddProfile }: CatalogueNoticeProps) {
  const { notice } = useCatalogueNotice()
  const acknowledge = useAcknowledgeNotice()
  const current = notice?.[part]
  if (!current) return null

  return (
    <Alert data-testid={`catalogue-notice-${part}`}>
      <Info className="h-4 w-4" />
      <AlertTitle className="flex items-center justify-between gap-2">
        {part === 'packaging' ? 'Standard packaging added' : 'Carrier postage'}
        <Button
          variant="ghost"
          size="icon"
          aria-label="Dismiss"
          onClick={() => acknowledge.mutate(part)}
          disabled={acknowledge.isPending}
        >
          <X className="h-4 w-4" />
        </Button>
      </AlertTitle>
      <AlertDescription className="text-sm">
        {part === 'packaging' ? (
          <PackagingBody notice={current as PackagingNotice} />
        ) : (
          <PostageBody
            notice={current as PostageNotice}
            carriers={carriers}
            onAddProfile={onAddProfile}
          />
        )}
      </AlertDescription>
    </Alert>
  )
}
