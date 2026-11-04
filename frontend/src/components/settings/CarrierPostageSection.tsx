/**
 * The carrier part of Settings → Postage (spec 006, US3).
 *
 * Batchivo ships published tariffs for a few carriers. This section shows the
 * shop's carrier and its services, lets an admin add or remove a service,
 * switch carrier (the old carrier's seeded profiles are superseded, never
 * edited), pick the default service a margin prices by, and accept a newer
 * tariff when one ships. When the shop's country or currency names no
 * carrier it can use, it says why and leaves the operator's own profiles to
 * do the work (FR-022).
 *
 * Postage is monetary policy (FR-007a): below admin it is read-only.
 */

import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CHOICE_REASONS } from '@/components/packaging/catalogueHelpers'
import {
  useApplyCarrier,
  useCarriers,
  useRemoveService,
  useSetDefaultService,
  useTariffUpdates,
} from '@/hooks/usePostageCatalogue'
import { apiErrorDetail } from '@/lib/apiError'
import { serviceKey } from '@/types/postageCatalogue'

import { carrierName } from '@/components/packaging/serviceLabels'

const CHEAPEST = '__cheapest__'

interface CarrierPostageSectionProps {
  canEdit: boolean
  /** Opens the panel's own "Add postage" form. */
  onAddProfile?: () => void
}

export function CarrierPostageSection({ canEdit, onAddProfile }: CarrierPostageSectionProps) {
  const { carriers: data, isLoading } = useCarriers()
  const { updates } = useTariffUpdates()
  const apply = useApplyCarrier()
  const remove = useRemoveService()
  const setDefault = useSetDefaultService()
  const [switchTo, setSwitchTo] = useState<string>('')

  if (isLoading || !data) {
    return (
      <div className="flex justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin" aria-label="Loading carriers" />
      </div>
    )
  }

  const all = data.carriers
  const currentKey = data.current.carrier
  const current = all.find((c) => c.key === currentKey) ?? null
  const seeded = current?.services.filter((s) => s.seeded) ?? []
  const others = all.filter((c) => c.usable && c.key !== currentKey)
  const suggested = all.find((c) => c.key === data.suggested_carrier) ?? null
  const busy = apply.isPending || remove.isPending || setDefault.isPending
  const error = apply.error ?? remove.error ?? setDefault.error

  return (
    <section className="space-y-3 rounded-md border p-4" data-testid="carrier-section">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-medium">Carrier tariff</h4>
        {current && (
          <span className="text-xs text-muted-foreground" data-testid="carrier-current">
            {current.name}
            {data.current.tariff_version ? `, tariff of ${data.current.tariff_version}` : ''}
          </span>
        )}
      </div>

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {apiErrorDetail(error)}
        </p>
      )}

      {!current && data.reason && (
        <p className="text-sm text-muted-foreground" data-testid="carrier-reason">
          {CHOICE_REASONS[data.reason]}{' '}
          {onAddProfile && canEdit ? (
            <>
              Enter your own with{' '}
              <Button variant="link" className="h-auto p-0" onClick={onAddProfile}>
                Add postage
              </Button>
              .
            </>
          ) : (
            'Enter your own postage profiles below.'
          )}
        </p>
      )}

      {!current && suggested && (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="carrier-suggestion">
          <span>
            {suggested.name} matches your shop&apos;s{' '}
            {data.chosen_from === 'country' ? 'country' : 'books currency'}.
          </span>
          {canEdit && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => apply.mutate({ carrier: suggested.key })}
            >
              Add {suggested.name} postage
            </Button>
          )}
        </div>
      )}

      {current && (
        <ul className="divide-y rounded-md border" data-testid="carrier-services">
          {current.services.map((s) => (
            <li key={s.key} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
              <span>
                {s.name}
                {s.seeded && (
                  <Badge variant="secondary" className="ml-2">
                    In use
                  </Badge>
                )}
              </span>
              {canEdit &&
                (s.seeded ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    aria-label={`Remove ${s.name}`}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Stop using ${s.name} from today? Orders already placed keep their postage.`,
                        )
                      ) {
                        remove.mutate(s.key)
                      }
                    }}
                  >
                    Remove
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    aria-label={`Add ${s.name}`}
                    onClick={() => apply.mutate({ carrier: current.key, services: [s.key] })}
                  >
                    Add
                  </Button>
                ))}
            </li>
          ))}
        </ul>
      )}

      {current && (
        <div className="space-y-1">
          <Label htmlFor="default-postage-service">Default service</Label>
          <Select
            value={data.current.default_service ?? CHEAPEST}
            disabled={!canEdit || busy}
            onValueChange={(value) => setDefault.mutate(value === CHEAPEST ? null : value)}
          >
            <SelectTrigger id="default-postage-service" aria-label="Default service">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={CHEAPEST}>Cheapest service that fits</SelectItem>
              {seeded.map((s) => (
                <SelectItem key={s.key} value={serviceKey(current.key, s.key)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Margins price postage by this service; a product can choose its own.
          </p>
        </div>
      )}

      {updates.map((u) => (
        <div
          key={`${u.carrier}-${u.latest}`}
          className="flex flex-wrap items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
          data-testid="tariff-update"
        >
          <span>
            A newer {carrierName(u.carrier, all)} tariff ({u.latest}) is available, replacing the
            one of {u.current} from {u.effective_from}. Orders already placed keep their postage.
          </span>
          {canEdit && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => apply.mutate({ carrier: u.carrier, tariff_version: u.latest })}
            >
              Use the new tariff
            </Button>
          )}
        </div>
      ))}

      {canEdit && current && others.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="space-y-1">
            <Label htmlFor="switch-carrier">Switch carrier</Label>
            <Select value={switchTo} onValueChange={setSwitchTo} disabled={busy}>
              <SelectTrigger id="switch-carrier" aria-label="Switch carrier" className="w-56">
                <SelectValue placeholder="Choose a carrier" />
              </SelectTrigger>
              <SelectContent>
                {others.map((c) => (
                  <SelectItem key={c.key} value={c.key}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={!switchTo || busy}
            onClick={() => {
              if (
                window.confirm(
                  `Switch to ${carrierName(switchTo, all)}? ${current.name}'s seeded postage stops from today.`,
                )
              ) {
                apply.mutate({ carrier: switchTo }, { onSuccess: () => setSwitchTo('') })
              }
            }}
          >
            Switch
          </Button>
        </div>
      )}
    </section>
  )
}
