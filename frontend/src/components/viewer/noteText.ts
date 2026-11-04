/**
 * A note's status as the operator reads it (spec 004, FR-027).
 */
import type { FileNote } from '@/types/model-file-version'

export function statusText(note: FileNote): string {
  if (note.status === 'resolved') return 'Resolved'
  if (note.status === 'carried_forward') return 'Carried forward'
  return 'Open'
}
