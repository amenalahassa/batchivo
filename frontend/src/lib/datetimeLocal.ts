/**
 * Values for `<input type="datetime-local">`.
 *
 * The input holds a wall-clock time with no zone, and `new Date(value)` reads
 * it back as local time. Filling it from `toISOString()` (UTC) shifted the time
 * by the browser's offset on every round trip: west of UTC a run's start moved
 * hours into the future (.specify/bugs/complete-run-timezone-500).
 */

/** `YYYY-MM-DDTHH:MM` in the browser's local time. */
export function toDateTimeLocalValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** The instant a datetime-local value names, as an ISO string (UTC). */
export function fromDateTimeLocalValue(value: string): string {
  return new Date(value).toISOString()
}
