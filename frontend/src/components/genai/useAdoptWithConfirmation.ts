/**
 * Adopt a generation result, asking first when it does not show the real item
 * (spec 008, FR-030).
 *
 * The server refuses an imagined picture going to a product with
 * `needs_confirmation`; this hook then opens `AdoptConfirmDialog` and, on
 * "Add anyway", sends the same adoption again with the confirmation. Spread
 * `confirmDialog` onto an `AdoptConfirmDialog`.
 */
import { useState } from 'react'

import { genaiError, useAdoptAsset } from '@/hooks/useGenAI'
import type { AdoptResponse, GenAIErrorDetail, JobTarget } from '@/types/genai'

interface Adoption {
  assetId: string
  target: JobTarget
}

export function useAdoptWithConfirmation(
  onAdopted?: (result: AdoptResponse, target: JobTarget) => void
) {
  const mutation = useAdoptAsset()
  const [awaiting, setAwaiting] = useState<Adoption | null>(null)

  const adopt = ({ assetId, target }: Adoption, confirm = false) => {
    mutation.mutate(
      { assetId, data: { target, confirm_not_real_item: confirm } },
      {
        onSuccess: (result) => onAdopted?.(result, target),
        onError: (error) => {
          if (genaiError(error)?.code === 'needs_confirmation') setAwaiting({ assetId, target })
        },
      }
    )
  }

  const detail = genaiError(mutation.error)
  const error: GenAIErrorDetail | null =
    detail && detail.code !== 'needs_confirmation' ? detail : null

  return {
    adopt: (assetId: string, target: JobTarget) => adopt({ assetId, target }),
    isPending: mutation.isPending,
    isSuccess: mutation.isSuccess,
    /** A refusal other than the confirmation request; `null` if none. */
    error,
    confirmDialog: {
      open: awaiting !== null,
      onCancel: () => setAwaiting(null),
      onConfirm: () => {
        const next = awaiting
        setAwaiting(null)
        if (next) adopt(next, true)
      },
    },
  }
}
