/** A part's intent as Preflight holds it (spec 009, US1). */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { IntentView } from './IntentView'
import { TEMPLATE_INTENT } from './preflightTestData'

const VALIDATION = {
  to_clarify: ['slug', 'function', 'loads[0].value'],
  unconfirmed: [{ field: 'loads[0]', status: 'déduit' }],
  missing: [],
}

describe('IntentView', () => {
  it('shows the fields, with placeholders highlighted', () => {
    render(<IntentView intent={TEMPLATE_INTENT} validation={VALIDATION} />)
    const fn = screen.getByText('Function').nextElementSibling as HTMLElement
    expect(fn).toHaveTextContent('[À PRÉCISER]')
    expect(fn.className).toContain('text-amber-700')
    expect(screen.getByText('Loads')).toBeInTheDocument()
    expect(screen.getByText('Interfaces')).toBeInTheDocument()
  })

  it('summarises what is left to clarify and confirm', () => {
    render(<IntentView intent={TEMPLATE_INTENT} validation={VALIDATION} />)
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('3 to clarify')
    expect(status).toHaveTextContent('loads[0] (déduit)')
  })

  it('marks unconfirmed value statuses', () => {
    render(<IntentView intent={TEMPLATE_INTENT} validation={VALIDATION} />)
    expect(screen.getAllByText('déduit').length).toBeGreaterThan(0)
    expect(screen.getByText('estimée')).toBeInTheDocument()
  })

  it('shows no summary when everything is settled', () => {
    render(
      <IntentView
        intent={{ ...TEMPLATE_INTENT, function: 'Tient un sac' }}
        validation={{ to_clarify: [], unconfirmed: [], missing: [] }}
      />
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText('Tient un sac')).toBeInTheDocument()
  })
})
