/**
 * The shop's country (spec 006, FR-021): optional, searchable, and used only
 * to choose the postage carrier -- it changes no price, zone or currency.
 *
 * Country names come from the browser (`Intl.DisplayNames`), so no list of
 * names is kept here, only the ISO 3166-1 alpha-2 codes.
 */

import { Combobox, type ComboboxOption } from '@/components/ui/combobox'

const CODES = (
  'AD AE AF AG AI AL AM AO AR AT AU AW AZ BA BB BD BE BF BG BH BI BJ BM BN BO BR BS BT BW BY BZ ' +
  'CA CD CF CG CH CI CL CM CN CO CR CU CV CY CZ DE DJ DK DM DO DZ EC EE EG ER ES ET FI FJ FM FO FR ' +
  'GA GB GD GE GG GH GI GL GM GN GQ GR GT GU GW GY HK HN HR HT HU ID IE IL IM IN IQ IR IS IT JE JM ' +
  'JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MG MH MK ML ' +
  'MM MN MO MT MU MV MW MX MY MZ NA NC NE NG NI NL NO NP NR NZ OM PA PE PF PG PH PK PL PR PS PT PW ' +
  'PY QA RO RS RU RW SA SB SC SD SE SG SI SK SL SM SN SO SR SS ST SV SY SZ TD TG TH TJ TL TM TN TO ' +
  'TR TT TV TW TZ UA UG US UY UZ VA VC VE VG VN VU WS XK YE ZA ZM ZW'
).split(' ')

function countryName(code: string): string {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) ?? code
  } catch {
    return code
  }
}

/** The searchable value of an option: its name and its code, so either can be typed. */
function optionValue(code: string): string {
  return `${countryName(code)} (${code})`
}

export const COUNTRY_OPTIONS: ComboboxOption[] = CODES.map((code) => ({
  value: optionValue(code),
  label: countryName(code),
})).sort((a, b) => a.label.localeCompare(b.label))

/** The ISO code an option's value ends with, whatever case the list handed back. */
function codeOf(value: string): string | null {
  const match = /\(([A-Za-z]{2})\)$/.exec(value)
  return match ? match[1].toUpperCase() : null
}

interface CountrySelectProps {
  value: string | null | undefined
  onChange: (code: string | null) => void
  disabled?: boolean
}

export function CountrySelect({ value, onChange, disabled }: CountrySelectProps) {
  const current = value ? COUNTRY_OPTIONS.find((o) => codeOf(o.value) === value.toUpperCase()) : undefined
  return (
    <Combobox
      options={COUNTRY_OPTIONS}
      value={current?.value ?? ''}
      // Picking the selected country again clears it: the field is optional.
      onValueChange={(next) => onChange(next ? codeOf(next) : null)}
      placeholder="No country set"
      searchPlaceholder="Search countries..."
      emptyText="No country found."
      disabled={disabled}
    />
  )
}
