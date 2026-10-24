/**
 * What the API said when it refused a request, in words a screen can show.
 *
 * FastAPI puts its reason in `detail`: a string for a plain refusal, an object
 * with a `message` for a structured one, and a list for a validation failure.
 * A screen that shows only "Request failed with status code 409" leaves the
 * operator guessing at a refusal the server already explained.
 */

import axios from 'axios'

export function apiErrorDetail(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((entry) => (entry && typeof entry === 'object' && 'msg' in entry ? entry.msg : ''))
        .filter(Boolean)
        .join('; ')
    }
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message: unknown }).message)
    }
  }
  return error instanceof Error ? error.message : 'The request failed'
}

/** The HTTP status of a refused request, where there was one. */
export function apiErrorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined
}
