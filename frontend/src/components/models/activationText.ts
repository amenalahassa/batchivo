/**
 * A figure of the activation review as the operator reads it (spec 004, T031).
 */
import type {
  ActivationField,
  ActivationRow,
  DimensionsValue,
  LineGrams,
  LineWeights,
} from "@/types/model-file-version";

function minutesText(value: string): string {
  const total = Number(value);
  if (!Number.isFinite(total)) return value;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

/** A figure as the operator reads it; "not set" for none. */
export function figureText(
  field: ActivationField,
  value: ActivationRow["current"] | ActivationRow["proposed"],
): string {
  if (value === null || value === undefined) return "not set";
  if (typeof value === "object") {
    if ("length_mm" in value) {
      const d = value as DimensionsValue;
      return `${d.length_mm} × ${d.width_mm} × ${d.height_mm} mm`;
    }
    // Several materials: each line its own grams (T065, T067).
    const grams: LineGrams =
      "labels" in value && typeof value.labels === "object"
        ? (value as LineWeights).labels
        : (value as LineGrams);
    return Object.entries(grams)
      .map(([name, g]) => `${name} ${g} g`)
      .join(", ");
  }
  if (field === "print_time_minutes") return minutesText(value);
  if (field === "weight_grams") return `${value} g`;
  return value;
}
