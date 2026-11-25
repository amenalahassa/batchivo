/**
 * Small helpers shared by the packaging screens.
 */

import type { ModelFile } from '@/lib/api/models'
import type { MeasurementOffer } from '@/components/products/DimensionsEditor'
import type {
  ConfirmParcelsInput,
  FileMeasurement,
  OrderPackagingSuggestions,
} from '@/types/packaging'

/** True while any file's measurement is still being made by the worker. */
export function anyMeasurementPending(files: { measurement?: FileMeasurement | null }[]) {
  return files.some((f) => f.measurement?.status === 'pending')
}

/** A parcel being edited in the dispatch dialog. */
export interface DraftParcel {
  containerId: string
  fillId: string | null
  fillQuantity: number
  contents: { sku: string; quantity: number }[]
}

/** The advisor's suggested parcels as editable rows. */
export function draftFrom(suggestions: OrderPackagingSuggestions | undefined): DraftParcel[] {
  return (suggestions?.parcels ?? []).map((p) => ({
    containerId: p.consumable_id,
    fillId: p.void_fill?.consumable_id ?? null,
    fillQuantity: p.void_fill?.quantity ?? 0,
    contents: p.contents.map((c) => ({ sku: c.sku, quantity: c.quantity })),
  }))
}

/** The edited rows as the confirm request sends them. */
export function toConfirmInput(parcels: DraftParcel[]): ConfirmParcelsInput {
  const several = parcels.length > 1
  return {
    parcels: parcels.map((p) => ({
      items: [
        { consumable_id: p.containerId, quantity: 1 },
        ...(p.fillId && p.fillQuantity > 0
          ? [{ consumable_id: p.fillId, quantity: p.fillQuantity }]
          : []),
      ],
      // Several parcels are each weighed with their own contents.
      contents: several && p.contents.length > 0 ? p.contents : null,
    })),
  }
}

/** File names by id, so a "measured from" badge can name its file. */
export function fileNamesOf(files: ModelFile[] | undefined): Record<string, string> {
  return Object.fromEntries((files ?? []).map((f) => [f.id, f.original_filename]))
}

/**
 * The newest file measurement that could be adopted, or null.
 *
 * Only a finished measurement with all three sizes qualifies; one still
 * pending, skipped or failed has nothing to offer.
 */
export function latestMeasurementOffer(files: ModelFile[] | undefined): MeasurementOffer | null {
  const measured = (files ?? [])
    .filter(
      (f) =>
        f.measurement?.status === 'done' &&
        f.measurement.length_mm !== null &&
        f.measurement.width_mm !== null &&
        f.measurement.height_mm !== null,
    )
    .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
  const newest = measured[0]
  if (!newest?.measurement) return null
  return {
    fileId: newest.id,
    fileName: newest.original_filename,
    length_mm: newest.measurement.length_mm as string,
    width_mm: newest.measurement.width_mm as string,
    height_mm: newest.measurement.height_mm as string,
  }
}
