/**
 * One model file's measured bounding box (T039, research D3).
 *
 * Shows the overall size, each object's for a multi-object 3MF, and the note
 * when there is one; "Measuring…" while a large file waits for the worker.
 */
import type { FileMeasurement } from '@/types/packaging'

const size = (l: string, w: string, h: string) => `${l} × ${w} × ${h} mm`

export function FileMeasurementSummary({
  measurement,
}: {
  measurement?: FileMeasurement | null
}) {
  if (!measurement) return null
  if (measurement.status === 'pending') {
    return <p className="text-xs text-muted-foreground">Measuring…</p>
  }
  const { length_mm, width_mm, height_mm } = measurement
  return (
    <div className="text-xs text-muted-foreground space-y-0.5">
      {length_mm && width_mm && height_mm && (
        <p>Measured {size(length_mm, width_mm, height_mm)}</p>
      )}
      {measurement.objects.length > 1 && (
        <ul className="pl-3 list-disc">
          {measurement.objects.map((o, i) => (
            <li key={`${o.name}-${i}`}>
              {o.name}: {size(o.length_mm, o.width_mm, o.height_mm)}
            </li>
          ))}
        </ul>
      )}
      {measurement.note && (
        <p className={measurement.status === 'done' ? undefined : 'text-amber-600'}>
          {measurement.note}
        </p>
      )}
    </div>
  )
}
