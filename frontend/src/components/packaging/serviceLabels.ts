/** Human names for '<carrier>:<service>' keys, from the carriers the API lists (spec 006). */

import type { Carrier } from '@/types/postageCatalogue'

export function serviceLabel(key: string, carriers?: Carrier[]): string {
  const [carrierKey, serviceKeyPart] = key.split(':')
  const carrier = carriers?.find((c) => c.key === carrierKey)
  const service = carrier?.services.find((s) => s.key === serviceKeyPart)
  if (carrier && service) return `${carrier.name} ${service.name}`
  return key
}

export function carrierName(key: string | null | undefined, carriers?: Carrier[]): string {
  if (!key) return ''
  return carriers?.find((c) => c.key === key)?.name ?? key
}
