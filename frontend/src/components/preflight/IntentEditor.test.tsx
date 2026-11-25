/** Editing a part's intent (spec 009, US1, clarification Q4). */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IntentEditor } from './IntentEditor'
import { composeIntentYaml } from './preflightLogic'
import { TEMPLATE_INTENT } from './preflightTestData'

describe('composeIntentYaml', () => {
  it('keeps the keys the form does not show and indents the blocks', () => {
    const text = composeIntentYaml(TEMPLATE_INTENT, {
      function: 'Tient un sac',
      category: 'crochet',
      quantity: '2',
      selling: true,
      sales_channel: 'etsy',
      country: 'FR',
      success_criteria: 'tient 5 kg\n\n  sans casse  ',
      loads: '- value: 5\n  unit: kg\n  status: validé',
      environment: 'max_temp_c: 80\nstatus: validé',
      interfaces: '',
    })
    expect(text).toContain('schema_version: 1\n')
    expect(text).toContain('slug: "[À PRÉCISER]"\n')
    expect(text).toContain('x_custom:\n  kept: true\n')
    expect(text).toContain('function: Tient un sac\n')
    expect(text).toContain('quantity: 2\n')
    expect(text).toContain('selling: true\n')
    expect(text).toContain('success_criteria:\n  - tient 5 kg\n  - sans casse\n')
    expect(text).toContain('loads:\n  - value: 5\n    unit: kg\n    status: validé\n')
    expect(text).toContain('environment:\n  max_temp_c: 80\n  status: validé\n')
    expect(text).not.toContain('interfaces:')
  })

  it('writes the placeholder for an empty field', () => {
    const text = composeIntentYaml(null, {
      function: '',
      category: '',
      quantity: '',
      selling: false,
      sales_channel: 'none',
      country: '',
      success_criteria: '',
      loads: '',
      environment: '',
      interfaces: '',
    })
    expect(text).toContain('function: "[À PRÉCISER]"')
    expect(text).toContain('quantity: "[À PRÉCISER]"')
  })
})

describe('IntentEditor', () => {
  it('starts from the stored intent and saves YAML', async () => {
    const onSave = vi.fn()
    render(
      <IntentEditor
        intent={{ ...TEMPLATE_INTENT, function: 'Tient un sac' }}
        saving={false}
        onSave={onSave}
        onCancel={vi.fn()}
      />
    )
    expect(screen.getByLabelText('Function')).toHaveValue('Tient un sac')
    expect((screen.getByLabelText('loads (YAML or JSON)') as HTMLTextAreaElement).value).toContain('unit: kg')
    await userEvent.clear(screen.getByLabelText('Country'))
    await userEvent.type(screen.getByLabelText('Country'), 'FR')
    await userEvent.click(screen.getByRole('button', { name: 'Save intent' }))
    expect(onSave).toHaveBeenCalledWith(expect.stringContaining('country: FR\n'))
  })

  it('shows the server error', () => {
    render(
      <IntentEditor
        intent={null}
        saving={false}
        error="intent_yaml.loads[0].duration: must be one of …"
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />
    )
    expect(screen.getByRole('alert')).toHaveTextContent('duration')
  })
})
