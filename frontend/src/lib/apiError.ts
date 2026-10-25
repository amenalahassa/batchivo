/**
 * What the API said when it refused a request, in words a screen can show.
 *
 * FastAPI puts its reason in `detail`: a string for a plain refusal, an object
 * with a `message` for a structured one, and a list for a validation failure.
 * A screen that shows only "Request failed with status code 409" leaves the
 * operator guessing at a refusal the server already explained.
 */

import axios from 'axios'

/**
 * A FastAPI `detail`, whatever its shape, as text -- or undefined when it says
 * nothing. Shared by the axios path below and by callers that use `fetch`
 * (`lib/auth.ts`, `lib/api/models.ts`), so the three shapes are read in one
 * place. Passing a list straight to `new Error` is what made the login page
 * show "[object Object]".
 */
export function detailText(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail.trim() || undefined
  if (Array.isArray(detail)) {
    const joined = detail
      .map((entry) => (entry && typeof entry === 'object' && 'msg' in entry ? String(entry.msg) : ''))
      .filter(Boolean)
      .join('; ')
    return joined || undefined
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return undefined
}

export function apiErrorDetail(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const text = detailText((error.response?.data as { detail?: unknown } | undefined)?.detail)
    if (text !== undefined) return text
  }
  return error instanceof Error ? error.message : 'The request failed'
}

/** The HTTP status of a refused request, where there was one. */
export function apiErrorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined
}
