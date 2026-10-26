/**
 * The "Packaging" section of the add and edit consumable dialogs (T029).
 *
 * A consumable that is packaging says what kind it is and, for a box or
 * mailer, its inner size, wall and empty weight; void fill says how much
 * volume one unit fills. Every figure is a decimal string, in mm, g or ml.
 */
import type { PackagingKind } from '@/types/packaging'
import type { PackagingProvenanceInput } from '@/types/consumable'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

export interface PackagingFields {
  packaging_kind?: PackagingKind | null
  inner_length_mm?: string | null
  inner_width_mm?: string | null
  inner_height_mm?: string | null
  wall_mm?: string | null
  empty_weight_grams?: string | null
  fill_volume_ml?: string | null
  packaging_provenance?: PackagingProvenanceInput | null
}

const NOT_PACKAGING = 'none'

const PACKAGING_KIND_LABELS: Record<PackagingKind, string> = {
  box: 'Box',
  mailer: 'Mailer',
  void_fill: 'Void fill',
  wrap: 'Wrap',
}

interface PackagingFieldsSectionProps {
  value: PackagingFields
  onChange: <K extends keyof PackagingFields>(field: K, value: PackagingFields[K]) => void
  /** Where each stored figure came from, as the API reports it (FR-038). */
  origins?: Record<string, string | null>
}

const ORIGIN_LABELS: Record<string, string> = { measured: 'Measured', assumed: 'Estimated' }

/** One badge for the stored figures' origin, or a mixed note when they differ. */
function OriginBadge({ origins }: { origins?: Record<string, string | null> }) {
  const sources = [...new Set(Object.values(origins ?? {}).filter((s): s is string => !!s))]
  if (sources.length === 0) return null
  const text = sources.length === 1 ? (ORIGIN_LABELS[sources[0]] ?? sources[0]) : 'Mixed origins'
  return <Badge variant="outline">{text}</Badge>
}

function MeasureInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string
  label: string
  value: string | null | undefined
  onChange: (value: string | null) => void
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        step="0.1"
        min="0"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      />
    </div>
  )
}

export function PackagingFieldsSection({ value, onChange, origins }: PackagingFieldsSectionProps) {
  const kind = value.packaging_kind ?? null
  const isContainer = kind === 'box' || kind === 'mailer'

  const setKind = (next: string) => {
    onChange('packaging_kind', next === NOT_PACKAGING ? null : (next as PackagingKind))
  }

  return (
    <div className="border-t pt-4 space-y-4">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium">Packaging</h4>
        {isContainer && <OriginBadge origins={origins} />}
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="packaging_kind">Packaging kind</Label>
          <Select value={kind ?? NOT_PACKAGING} onValueChange={setKind}>
            <SelectTrigger id="packaging_kind" aria-label="Packaging kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NOT_PACKAGING}>Not packaging</SelectItem>
              {(Object.keys(PACKAGING_KIND_LABELS) as PackagingKind[]).map((k) => (
                <SelectItem key={k} value={k}>
                  {PACKAGING_KIND_LABELS[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {isContainer && (
          <div className="space-y-2">
            <Label htmlFor="packaging_provenance">How do you know these figures?</Label>
            <Select
              value={value.packaging_provenance?.source ?? 'assumed'}
              onValueChange={(source) =>
                onChange('packaging_provenance', {
                  source: source as PackagingProvenanceInput['source'],
                })
              }
            >
              <SelectTrigger id="packaging_provenance" aria-label="How do you know these figures?">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="measured">Measured</SelectItem>
                <SelectItem value="assumed">Estimated (supplier listing)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {isContainer && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <MeasureInput
              id="inner_length_mm"
              label="Inner length (mm)"
              value={value.inner_length_mm}
              onChange={(v) => onChange('inner_length_mm', v)}
            />
            <MeasureInput
              id="inner_width_mm"
              label="Inner width (mm)"
              value={value.inner_width_mm}
              onChange={(v) => onChange('inner_width_mm', v)}
            />
            <MeasureInput
              id="inner_height_mm"
              label={kind === 'mailer' ? 'Max thickness (mm)' : 'Inner height (mm)'}
              value={value.inner_height_mm}
              onChange={(v) => onChange('inner_height_mm', v)}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <MeasureInput
              id="wall_mm"
              label="Wall (mm)"
              value={value.wall_mm}
              onChange={(v) => onChange('wall_mm', v)}
            />
            <MeasureInput
              id="empty_weight_grams"
              label="Empty weight (g)"
              value={value.empty_weight_grams}
              onChange={(v) => onChange('empty_weight_grams', v)}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            The advisor suggests this {kind} only once all three inner sizes are set.
          </p>
        </>
      )}

      {kind === 'void_fill' && (
        <div className="grid grid-cols-2 gap-4">
          <MeasureInput
            id="fill_volume_ml"
            label="Fill volume per unit (ml)"
            value={value.fill_volume_ml}
            onChange={(v) => onChange('fill_volume_ml', v)}
          />
        </div>
      )}
    </div>
  )
}
