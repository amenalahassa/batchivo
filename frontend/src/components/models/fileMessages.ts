/**
 * What the model files screens say when a file cannot be measured or a change
 * is refused, in the operator's words (spec 004, FR-004, FR-015, FR-016).
 */
import axios from 'axios'

import { apiErrorDetail } from '@/lib/apiError'
import type { FileMeasurement } from '@/types/packaging'

export const SLICED_NO_GEOMETRY =
  "This is a sliced plate. It holds the print, not the part's shape, so it can't be measured. " +
  'Upload the project .3mf (Bambu Studio: File → Save project) or the .stl.'

export const NO_GEOMETRY =
  "This file has no part in it to measure. Upload the project .3mf (Bambu Studio: File → Save project) or the .stl."

export const UNREADABLE =
  "This file couldn't be read as a 3D model. Check it opens in your slicer, then upload it again or upload the .stl."

export const TOO_LARGE =
  'This file is too large to measure here. Enter the dimensions by hand, or upload a lighter .stl of the part.'

/** The plain-language reason a file was not measured, or null when the note says enough. */
export function measurementProblem(
  measurement: Pick<FileMeasurement, 'reason'>,
  isSliced?: boolean
): string | null {
  switch (measurement.reason) {
    case 'no_geometry':
      return isSliced === false ? NO_GEOMETRY : SLICED_NO_GEOMETRY
    case 'unreadable':
      return UNREADABLE
    case 'too_large':
      return TOO_LARGE
    default:
      return null
  }
}

/** The refusals the API gives, in the operator's words. */
const REFUSALS: Record<string, string> = {
  last_file_of_active_version:
    "This is the active version's only file. Make another version active before deleting it.",
  active_print_file:
    "This is the active version's print file. Choose another print file, or make another version active, before deleting it.",
}

export function refusalMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      const code = String((detail as { code: unknown }).code)
      if (REFUSALS[code]) return REFUSALS[code]
    }
  }
  return apiErrorDetail(error)
}
