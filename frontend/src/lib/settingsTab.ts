/** Which Settings tab opens first (spec 008, US1 AS5). */

const TABS = ['general', 'pricing', 'payments', 'marketplace', 'team', 'ai', 'api-tokens'] as const
export type SettingsTab = (typeof TABS)[number]

/**
 * The tab named by `?tab=` (e.g. `/settings?tab=ai` from the generate
 * dialog, spec 008 US1 AS5), or `general`. Only known tabs are honoured, and
 * `ai` only for someone who can see it. Settings passes `window.location.search`, so it
 * works whether or not the route declares a search schema.
 */
export function initialSettingsTab(search: string, canSeeAI: boolean): SettingsTab {
  const asked = new URLSearchParams(search).get('tab')
  const known = TABS.find((tab) => tab === asked)
  if (!known || (known === 'ai' && !canSeeAI)) return 'general'
  return known
}
