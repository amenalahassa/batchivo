/**
 * Onboarding step 5: standard packaging and carrier postage (spec 006, US2/US3).
 *
 * The whole packaging catalogue starts selected and can be thinned or skipped
 * (FR-010). The carrier is pre-selected from the shop's country, else its
 * books currency (FR-017, FR-021); when neither names a carrier Batchivo has
 * a tariff for, the step says why and adds no postage (FR-022). The default
 * service is optional: without one, a margin uses the cheapest service that
 * fits.
 */

import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { CatalogueItemPicker } from '@/components/packaging/CatalogueItemPicker'
import { CHOICE_REASONS, selectableKeys } from '@/components/packaging/catalogueHelpers'
import { symbolForCurrency } from '@/lib/money'
import { usePackagingCatalogue } from '@/hooks/usePackagingCatalogue'
import { useCarriers } from '@/hooks/usePostageCatalogue'
import type { OnboardingStep5Request } from '@/lib/api/onboarding'
import { serviceKey } from '@/types/postageCatalogue'

const NO_CARRIER = '__none__'
const CHEAPEST = '__cheapest__'

interface PackagingPostageStepProps {
  onSubmit: (data: OnboardingStep5Request) => void
  onBack: () => void
  isLoading?: boolean
}

export function PackagingPostageStep({ onSubmit, onBack, isLoading }: PackagingPostageStepProps) {
  const { catalogue, isLoading: loadingCatalogue } = usePackagingCatalogue()
  const { carriers, isLoading: loadingCarriers } = useCarriers()

  const [packaging, setPackaging] = useState<Set<string>>(new Set())
  const [carrier, setCarrier] = useState<string>(NO_CARRIER)
  const [services, setServices] = useState<Set<string>>(new Set())
  const [defaultService, setDefaultService] = useState<string>(CHEAPEST)

  useEffect(() => {
    if (catalogue) setPackaging(new Set(selectableKeys(catalogue.items)))
  }, [catalogue])

  const usable = useMemo(() => (carriers?.carriers ?? []).filter((c) => c.usable), [carriers])
  const chosen = usable.find((c) => c.key === carrier)

  // Pre-select the carrier the country (or currency) names.
  useEffect(() => {
    if (carriers) setCarrier(carriers.suggested_carrier ?? NO_CARRIER)
  }, [carriers])

  useEffect(() => {
    setServices(new Set(chosen?.services.map((s) => s.key) ?? []))
    setDefaultService(CHEAPEST)
  }, [chosen])

  const toggle = (setter: typeof setPackaging) => (key: string, checked: boolean) =>
    setter((prev) => {
      const next = new Set(prev)
      if (checked) next.add(key)
      else next.delete(key)
      return next
    })

  const submit = () => {
    onSubmit({
      packaging_keys: [...packaging],
      carrier: chosen ? chosen.key : null,
      services: chosen ? [...services] : [],
      default_service:
        chosen && defaultService !== CHEAPEST && services.has(defaultService.split(':')[1])
          ? defaultService
          : null,
    })
  }

  if (loadingCatalogue || loadingCarriers) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin" aria-label="Loading" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h3 className="font-medium">Standard packaging</h3>
        <p className="text-sm text-muted-foreground">
          Common boxes, mailers and fill with typical sizes and costs, marked as defaults until you
          measure them. Clear any you do not use.
        </p>
        {catalogue && (
          <CatalogueItemPicker
            items={catalogue.items}
            selected={packaging}
            onToggle={toggle(setPackaging)}
            // The catalogue prices in the currency step 3 just saved.
            currencySymbol={symbolForCurrency(catalogue.currency)}
          />
        )}
      </section>

      <section className="space-y-3">
        <h3 className="font-medium">Postage</h3>
        {carriers?.reason && (
          <p className="text-sm text-muted-foreground" data-testid="carrier-reason">
            {CHOICE_REASONS[carriers.reason]} You can enter your own postage profiles in Settings
            later.
          </p>
        )}
        <div className="space-y-2">
          <Label htmlFor="onboarding-carrier">Carrier</Label>
          <Select value={carrier} onValueChange={setCarrier} disabled={isLoading}>
            <SelectTrigger id="onboarding-carrier" aria-label="Carrier">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_CARRIER}>No carrier postage</SelectItem>
              {usable.map((c) => (
                <SelectItem key={c.key} value={c.key}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {chosen && carriers && chosen.key === carriers.suggested_carrier && (
            <p className="text-xs text-muted-foreground" data-testid="carrier-chosen-from">
              Suggested from your shop&apos;s{' '}
              {carriers.chosen_from === 'country' ? 'country' : 'books currency'}.
            </p>
          )}
        </div>

        {chosen && (
          <>
            <ul className="space-y-1" data-testid="carrier-services">
              {chosen.services.map((s) => (
                <li key={s.key} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    id={`service-${s.key}`}
                    checked={services.has(s.key)}
                    onCheckedChange={(checked) => toggle(setServices)(s.key, checked === true)}
                    aria-label={s.name}
                  />
                  <label htmlFor={`service-${s.key}`}>{s.name}</label>
                </li>
              ))}
            </ul>
            <div className="space-y-2">
              <Label htmlFor="onboarding-default-service">Default service</Label>
              <Select value={defaultService} onValueChange={setDefaultService} disabled={isLoading}>
                <SelectTrigger id="onboarding-default-service" aria-label="Default service">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={CHEAPEST}>Cheapest service that fits</SelectItem>
                  {chosen.services
                    .filter((s) => services.has(s.key))
                    .map((s) => (
                      <SelectItem key={s.key} value={serviceKey(chosen.key, s.key)}>
                        {s.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            {chosen.source && (
              <p className="text-xs text-muted-foreground">
                Tariff of {chosen.latest_tariff}: {chosen.source}
              </p>
            )}
          </>
        )}
      </section>

      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="outline" onClick={onBack} disabled={isLoading}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => onSubmit({ skip: true })} disabled={isLoading}>
            Skip for now
          </Button>
          <Button onClick={submit} disabled={isLoading}>
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="mr-2 h-4 w-4" />
            )}
            Finish setup
          </Button>
        </div>
      </div>
    </div>
  )
}
